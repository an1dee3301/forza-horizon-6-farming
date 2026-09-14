"""Mission-scoped operational rates; estimates never authorize inputs."""
import math
from collections import defaultdict
from datetime import datetime
from statistics import median


def numeric(v):
    return type(v) in (int, float) and math.isfinite(v)


def percentiles(values):
    values=sorted(v for v in values if numeric(v) and v>=0)
    return dict(n=len(values), **{f'p{p}': (median(values) if p == 50 else values[max(0,math.ceil(p/100*len(values))-1)]) if values else None
                                 for p in (50,90,99)})


def failure_cause(message, stage=''):
    text=str(message).lower()
    if 'network connection was lost' in text or 'network diagnostics' in text:
        return 'network_disconnect'
    if 'selected car card' in text: return 'car_selection_detection'
    if 'could not identify keyboard focus' in text: return 'menu_focus_detection'
    if 'focus' in text: return 'focus_lost'
    if any(x in text for x in ('crash','terminated unexpectedly','fhc11')): return 'game_crash'
    if any(x in text for x in ('ocr','read the available','read skill','unreadable')): return 'OCR_fail'
    if any(x in text for x in ('untouched','recently added did not','no recent mad','not found')): return 'car_not_found'
    if any(x in text for x in ('purchase','receipt','credits','transaction')): return 'purchase_fail'
    if 'timed out' in text or 'timeout' in text:
        if 'free-roam pause menu' in text: return 'pause_menu_timeout'
        # Expected-screen lists can contain "mastery" during a return timeout.
        # The actual active stage determines this failure's category.
        return {'choose':'choose_timeout','return':'return_timeout','open_mastery':'mastery_detection','mastery':'mastery_detection','buy':'purchase_fail'}.get(stage,'screen_timeout')
    if any(x in text for x in ('mastery','node','selection is ambiguous')): return 'mastery_detection'
    if 'expected' in text or 'unexpected' in text: return 'unexpected_screen'
    return 'other'


def _actual_farm_balance(row):
    before,after,gain=(row.get(k) for k in ('before_sp','after_sp','gained_sp'))
    return (type(before) is int and type(after) is int and 0<=before<=after<=999
            and numeric(gain) and gain==after-before)


def _loss_cohort(row):
    """Unknown challenge identity and incompatible timer bases never get pooled."""
    code=row.get('share_code')
    if not isinstance(code,str) or len(code)!=9 or not code.isascii() or not code.isdigit():
        return None
    drive=row.get('drive_seconds')
    active=row.get('active_seconds')
    if numeric(drive) and drive>0:
        return (code,'drive_seconds'),drive
    if drive is not None:
        return None
    if numeric(active) and active>0:
        return (code,'active_seconds'),active
    return None


def _mission_farm_rows(goal,source):
    """Preserve history order and all outcomes before selecting a profile regime."""
    mission=goal.get('id')
    farms=[]
    for row in source.get('farms',[]):
        if mission:
            row_goal=row.get('goal_id')
            row_id=row.get('id')
            if row_goal is not None:
                belongs=row_goal==mission
            elif isinstance(row_id,str):
                belongs=row_id.startswith(mission+'_')
            else:
                belongs=source.get('goal_id')==mission
            if not belongs:
                continue
        farms.append(row)
    return farms


def cap_loss_metrics(goal,source):
    """Estimate cap loss per the exact same covered whole-farm active hours.

    `farms` contains completed farm records. Partial timing is retained in the
    cumulative estimate where supported, but never supplies a rate denominator.
    Explicit uncapped zero with consistent actual balances does not invent raw
    SP when the old estimator underpredicted the amount actually retained.
    """
    farms=[row for row in _mission_farm_rows(goal,source)
           if row.get('phase') in (None,'complete')]
    cohorts=defaultdict(list)
    for row in farms:
        cohort=_loss_cohort(row)
        if (cohort is not None and not row.get('partial_timing') and _actual_farm_balance(row)
                and row.get('capped') is False and row['after_sp']<999
                and row.get('exit_reason','natural_completion')=='natural_completion'
                and row['gained_sp']>0):
            key,seconds=cohort
            cohorts[key].append(row['gained_sp']/seconds)
    estimates=[]
    for row in farms:
        raw,loss=row.get('raw_estimated_sp'),row.get('estimated_cap_loss_sp')
        gain=row.get('gained_sp')
        valid_raw=(numeric(raw) and raw>=0 and (not numeric(gain) or raw>=gain))
        valid_pair=(valid_raw and numeric(loss) and 0<=loss<=raw
                    and (not numeric(gain) or math.isclose(raw-gain,loss,abs_tol=1e-6)
                         or loss==0 and row.get('capped') is False))
        actual=_actual_farm_balance(row)
        if valid_pair and actual:
            valid_pair=((row.get('capped') is True and row['after_sp']==999)
                        or (row.get('capped') is False and row['after_sp']<999 and loss==0))
        if valid_pair:
            estimate=dict(loss=loss,raw=raw,source='recorded_estimate')
        elif (numeric(loss) and loss==0 and actual and row.get('capped') is False and row['after_sp']<999):
            # This zero is supported by the actual uncapped balance, even if
            # an older forecast was below observed gain. Never raise raw to gain.
            estimate=dict(loss=0,raw=raw if valid_raw else None,source='verified_uncapped_zero')
        else:
            estimate=dict(loss=None,raw=None,source='unsupported')
            cohort=_loss_cohort(row)
            if (actual and row.get('capped') is True and row['after_sp']==999
                    and not row.get('partial_timing')
                    and row.get('exit_reason','natural_completion')=='natural_completion'
                    and cohort is not None):
                key,seconds=cohort
                rates=cohorts[key]
                if len(rates)>=3:
                    predicted=median(rates)*seconds
                    if predicted>=gain:
                        estimate=dict(loss=predicted-gain,raw=predicted,
                                      source='same_profile_'+key[1]+'_cohort')
        estimates.append((row,estimate))
    supported=[e for _,e in estimates if numeric(e['loss'])]
    raw_supported=[e for e in supported if numeric(e['raw'])]
    raw_total=sum(e['raw'] for e in raw_supported)
    raw_loss=sum(e['loss'] for e in raw_supported)
    covered=[]
    excluded=dict(partial_timing=0,missing_or_invalid_timing=0,unsupported_estimate=0)
    for row,estimate in estimates:
        seconds=row.get('active_seconds')
        if row.get('partial_timing'):
            excluded['partial_timing']+=1
        elif not numeric(seconds) or seconds<=0:
            excluded['missing_or_invalid_timing']+=1
        elif not numeric(estimate['loss']):
            excluded['unsupported_estimate']+=1
        else:
            covered.append((row,estimate))
    seconds=sum(row['active_seconds'] for row,_ in covered)
    lost=sum(e['loss'] for _,e in covered)
    per_hour=lost*3600/seconds if seconds>0 else None
    capped=lambda row: row.get('capped') is True or row.get('after_sp')==999
    capped_runs=sum(capped(row) for row in farms)
    covered_capped=sum(capped(row) for row,_ in covered)
    unknown_capped=sum(capped(row) and not numeric(e['loss']) for row,e in estimates)
    uncovered_capped=capped_runs-covered_capped
    headline_rate=per_hour if uncovered_capped==0 else None
    return dict(cap_loss_sp_estimated=sum(e['loss'] for e in supported) if supported else None,
        cap_loss_samples=len(supported),cap_loss_raw_samples=len(raw_supported),
        cap_loss_percent_estimated=100*raw_loss/raw_total if raw_total>0 else None,
        cap_loss_sp_farm_hour_estimated=headline_rate,
        cap_loss_mazda_farm_hour_estimated=headline_rate/21 if headline_rate is not None else None,
        cap_loss_covered_sp_farm_hour_estimated=per_hour,
        cap_loss_covered_mazda_farm_hour_estimated=per_hour/21 if per_hour is not None else None,
        cap_loss_unknown_capped_runs=unknown_capped,
        cap_loss_rate_uncovered_capped_runs=uncovered_capped,
        cap_loss_rate_capped_runs=capped_runs,cap_loss_rate_covered_capped_runs=covered_capped,
        cap_loss_rate_samples=len(covered),cap_loss_rate_seconds=seconds,
        cap_loss_rate_sp_estimated=lost if covered else None,cap_loss_rate_total_runs=len(farms),
        cap_loss_rate_coverage_percent=100*len(covered)/len(farms) if farms else None,
        cap_loss_rate_excluded=excluded,
        cap_loss_estimation_sources=dict((name,sum(e['source']==name for _,e in estimates))
                                        for name in sorted({e['source'] for _,e in estimates})))


def recent_cap_loss_metrics(goal,source):
    """Current contiguous Mega regime, not an outcome-selected or mission rate.

    Select the boundary before validating outcomes or timing. Unknown profile
    rows stay in the segment and retain their unknown identity for estimation.
    """
    fields=('share_code','cohort_start_id','sp_farm_hour_estimated',
            'mazda_farm_hour_estimated','rate_samples','rate_seconds','total_runs',
            'partial_timing_runs','unknown_capped_runs','sp_estimated','samples')
    empty={'recent_cap_loss_'+name:None for name in fields}
    farms=_mission_farm_rows(goal,source)
    explicit=[(i,row['share_code']) for i,row in enumerate(farms)
              if isinstance(row.get('share_code'),str) and len(row['share_code'])==9
              and row['share_code'].isascii() and row['share_code'].isdigit()]
    if not explicit or explicit[-1][1]!='155439962':
        return empty
    start=max((i+1 for i,code in explicit if code!='155439962'),default=0)
    segment=farms[start:]
    metrics=cap_loss_metrics(goal,dict(source,farms=segment))
    # Missing outcomes cannot silently imply zero cap loss. Keep these rows in
    # coverage, but do not label an incomplete-outcome regime with a zero rate.
    missing_outcome=any(not _actual_farm_balance(row) for row in segment
                        if row.get('phase') in (None,'complete'))
    per_hour=None if missing_outcome else metrics['cap_loss_sp_farm_hour_estimated']
    values=dict(share_code='155439962',cohort_start_id=segment[0].get('id'),
        sp_farm_hour_estimated=per_hour,
        mazda_farm_hour_estimated=per_hour/21 if per_hour is not None else None,
        rate_samples=metrics['cap_loss_rate_samples'],rate_seconds=metrics['cap_loss_rate_seconds'],
        total_runs=metrics['cap_loss_rate_total_runs'],
        partial_timing_runs=metrics['cap_loss_rate_excluded']['partial_timing'],
        unknown_capped_runs=metrics['cap_loss_unknown_capped_runs'],
        sp_estimated=metrics['cap_loss_sp_estimated'],samples=metrics['cap_loss_samples'])
    return {'recent_cap_loss_'+name:value for name,value in values.items()}


def summarize(goal, source, now=None):
    now=now or datetime.now().astimezone()
    cycles=source.get('cycles',[])
    recent=cycles[-20:]
    current_cycle=percentiles(r.get('elapsed_seconds') for r in recent)
    previous_cycle=percentiles(r.get('elapsed_seconds') for r in cycles[-40:-20])
    comparison=dict(current=current_cycle,previous=previous_cycle,
        percent_delta={k:(100*(current_cycle[k]/previous_cycle[k]-1)
            if numeric(current_cycle[k]) and numeric(previous_cycle[k]) and previous_cycle[k]>0 else None)
            for k in ('p50','p90')},basis='latest 20 versus preceding 20 retained completed cars; lower is faster')
    stages={name:percentiles(r.get('steps',{}).get(name) for r in recent)
            for name in ('buy','choose','open_mastery','mastery','return')}
    active=sum(v for v in source.get('seconds',{}).values() if numeric(v) and v>=0) or goal.get('active_seconds',0)
    wall=None
    try:
        start=datetime.fromisoformat(goal['started_at'])
        if start.tzinfo is None: start=start.astimezone()
        wall=max(0,(now-start).total_seconds())
    except (KeyError,TypeError,ValueError): pass
    earned=goal.get('rewards',0)
    rate=lambda n,d: n*3600/d if numeric(d) and d>0 else None
    farms=source.get('farms',[])
    # Select the current profile regime BEFORE timing/outcome eligibility.
    # A quick Mini trial must not alter the apparent capacity of current Mega.
    explicit=[(i,r.get('share_code')) for i,r in enumerate(farms)
              if isinstance(r.get('share_code'),str) and len(r['share_code'])==9
              and r['share_code'].isascii() and r['share_code'].isdigit()]
    code=explicit[-1][1] if explicit else None
    start=max((i+1 for i,c in explicit if c!=code),default=0)
    regime=farms[start:]
    eligible=[r for r in regime if code is not None and r.get('share_code')==code
              and not r.get('partial_timing') and _actual_farm_balance(r)
              and numeric(r.get('active_seconds')) and r['active_seconds']>0]
    farm_sp=sum(r['gained_sp'] for r in eligible)
    farm_seconds=sum(r['active_seconds'] for r in eligible)
    sp_hour=rate(farm_sp,farm_seconds)
    conversion_rows=cycles[-80:]
    conversion_seconds=sum(r['elapsed_seconds'] for r in conversion_rows if numeric(r.get('elapsed_seconds')) and r['elapsed_seconds']>0)
    conversion_n=sum(numeric(r.get('elapsed_seconds')) and r['elapsed_seconds']>0 for r in conversion_rows)
    conversion=rate(conversion_n,conversion_seconds)
    farm_capacity=sp_hour/21 if sp_hour is not None else None
    capacities=[farm_capacity,conversion]
    valid=all(numeric(v) and v>0 for v in capacities)
    causes=defaultdict(lambda:dict(count=0,recovery_seconds=0,costs=[]))
    failures=[dict(r,cause=failure_cause(r.get('message',''),r.get('stage','')))
              if r.get('cause') in {'other','OCR_fail'} and r.get('message') else r
              for r in source.get('failures',[])]
    for row in failures:
        c=causes[row['cause']]; c['count']+=1
        if numeric(row.get('recovery_seconds')):
            c['recovery_seconds']+=row['recovery_seconds']; c['costs'].append(row['recovery_seconds'])
    covered=[r for r in cycles if r.get('recovery_tracking_version')==2] if not source.get('telemetry_dropped') else []
    covered_keys={(r['batch_id'],r['cycle']) for r in covered}
    for name,c in causes.items():
        c['per_100_cars']=100*sum(r['cause']==name and (r.get('batch_id'),r.get('cycle')) in covered_keys for r in failures)/len(covered) if covered else None
        c['cost']=percentiles(c.pop('costs'))
    legacy=source.get('legacy_retry_count',source.get('retries',0))
    if legacy:
        causes['legacy_unclassified']=dict(count=legacy,recovery_seconds=None,per_100_cars=None,cost=percentiles([]))
    loss_metrics=cap_loss_metrics(goal,source)
    recent_loss_metrics=recent_cap_loss_metrics(goal,source)
    transitions=source.get('transitions',[])
    tax_rows=[]
    for row in cycles if not source.get('telemetry_dropped') else []:
        timing=row.get('transition_timing') or {}
        residual=timing.get('unassigned_within_usable_seconds')
        observed=timing.get('observed_usable_seconds')
        elapsed=row.get('elapsed_seconds')
        if (timing.get('version')==2 and numeric(timing.get('usable_count')) and timing['usable_count']>0
                and all(numeric(v) for v in (residual,observed,elapsed))
                and 0<=residual<=observed<=elapsed and elapsed>0):
            tax_rows.append(row)
    tax_seconds=sum(r['elapsed_seconds'] for r in tax_rows)
    tax_residual=sum(r['transition_timing']['unassigned_within_usable_seconds'] for r in tax_rows)
    tax_coverage=dict(n=len(tax_rows),total=len(cycles),cycle_seconds=tax_seconds,residual_seconds=tax_residual,
        usable_count=sum(r['transition_timing']['usable_count'] for r in tax_rows),
        partial_count=sum(r['transition_timing'].get('partial_count',0) for r in tax_rows))
    transition_stages={}
    for name in stages:
        rows=[r for r in transitions if r.get('stage')==name and r.get('outcome')=='usable']
        transition_stages[name]={k:percentiles(r.get(k) for r in rows) for k in ('input_to_change','change_to_usable','input_to_usable')}
    boundary_rows=[r for r in source.get('boundaries',[]) if isinstance(r,dict)][-100:]
    boundary_metrics={}
    for name in sorted({r.get('name') for r in boundary_rows if isinstance(r.get('name'),str)}):
        rows=[r for r in boundary_rows if r.get('name')==name]
        measured=[r.get('seconds') for r in rows if r.get('success') is True]
        boundary_metrics[name]=dict(**percentiles(measured),total_seconds=sum(v for v in measured if numeric(v)),
                                    failures=sum(r.get('success') is not True for r in rows))
    window=source.get('open_system_window') or {}
    window_seconds=window.get('active_seconds')
    window_start,window_current=window.get('rewards_start'),window.get('current_rewards')
    window_rewards=(window_current-window_start if type(window_start) is int and type(window_current) is int
                    and window_current>=window_start else None)
    window_rate=rate(window_rewards,window_seconds) if numeric(window_rewards) else None
    combined=1/(1/farm_capacity+1/conversion) if valid else None
    capacity_gap=(combined-window_rate if numeric(combined) and numeric(window_rate) else None)
    return dict(stage_percentiles=stages,cycle_percentiles=current_cycle,cycle_comparison=comparison,
        sw_active_hour=rate(earned,active),sw_wall_hour=rate(earned,wall),wall_seconds=wall,
        retained_sp_hour=sp_hour,farm_capacity=farm_capacity,conversion_capacity=conversion,
        rate_coverage=dict(farm_n=len(eligible),farm_total=len(regime),farm_seconds=farm_seconds,
            farm_profile=next((r.get('profile_name') for r in reversed(eligible) if r.get('profile_name')),code),
            farm_share_code=code,farm_scope='current contiguous profile regime; complete active timing',
            conversion_n=conversion_n,conversion_total=len(conversion_rows),conversion_seconds=conversion_seconds,
            conversion_scope='last 80 recorded cars including interruptions',active_seconds=active,wall_seconds=wall,
            active_basis='recorded activity; historical missing intervals not reconstructed'),
        farm_rate_samples=len(eligible),conversion_rate_samples=conversion_n,
        bottleneck=('SP FARM' if farm_capacity<conversion else 'CONVERSION' if conversion<farm_capacity else 'BALANCED') if valid else 'MEASURING',
        imbalance_percent=(1-min(capacities)/max(capacities))*100 if valid else None,
        combined_capacity=combined,
        current_system_active_hour=window_rate,current_system_rewards=window_rewards,
        current_system_active_seconds=window_seconds,
        system_capacity_gap=capacity_gap,
        system_capacity_loss_percent=(100*capacity_gap/combined if numeric(capacity_gap) and combined>0 else None),
        boundary_metrics=boundary_metrics,boundary_samples=len(boundary_rows),
        first_pass_yield=100*sum(not r.get('recovery_events',0) for r in covered)/len(covered) if covered else None,
        first_pass_samples=len(covered),legacy_zero_interruption_percent=100*sum(not r.get('failed_attempts',0) for r in cycles)/len(cycles) if cycles else None,
        forza_tax_percent_estimated=100*tax_residual/tax_seconds if tax_seconds>0 else None,
        forza_tax_coverage=tax_coverage,
        failures=dict(causes),**loss_metrics,**recent_loss_metrics,
        transition_stages=transition_stages,
        transition_coverage={name:dict(usable=sum(r.get('stage')==name and r.get('outcome')=='usable' for r in transitions),
                                      total=sum(r.get('stage')==name for r in transitions)) for name in stages},
        attribution_coverage={k:sum(numeric(r.get('attribution',{}).get(k)) for r in covered)
            for k in ('automation_decision','recovery','waiting_loading_estimate','unattributed')},
        attribution={k:(sum(values) if (values:=[r.get('attribution',{}).get(k) for r in covered
            if numeric(r.get('attribution',{}).get(k))]) else None)
            for k in ('automation_decision','recovery','waiting_loading_estimate','unattributed')},
        mandatory_ui_seconds=None)


def fmt(value, suffix=''):
    return f'{value:.1f}{suffix}' if numeric(value) else 'Measuring'
