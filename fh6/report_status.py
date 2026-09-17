"""Numeric Discord scorecard; definitions and historical detail stay on the boards."""
from .operations_metrics import numeric, fmt
from .inventory import inventory_summary
from .farm_notices import discord_time, projected_time


def duration(value):
    if not numeric(value) or value < 0: return '—'
    seconds = int(value)
    if seconds < 60: return f'{seconds}s'
    if seconds < 3600: return f'{seconds//60}:{seconds%60:02d}'
    return f'{seconds//3600}h {(seconds%3600)//60:02d}m'


def status_text(data):
    a=data.get('analytics') or {}; source=data.get('charts') or {}
    op=a.get('operations',{}) if source.get('goal_id')==data.get('goal_id') else {}
    account=data.get('account') or {}; q=op.get('cycle_percentiles') or {}
    money=lambda v:f'{v/1e6:,.2f}M' if numeric(v) else '—'
    value=lambda v:f'{v:,}' if type(v) is int else '—'
    credits,cost=account.get('credits'),a.get('credits_required')
    earned,bought=data.get('earned',0),data.get('bought',0)
    budget=data.get('credit_budget_estimate') or {}; inventory=inventory_summary(data)
    # Credit-limited runs already expose one canonical, guarded balance in
    # credit_budget_estimate.  It is selected from the newest valid account or
    # purchase-adjusted budget proof.  Formatting the raw account OCR here can
    # resurrect a truncated suffix (for example 6,191,170 -> 6,191) even after
    # the purchasing guard correctly rejected it.
    report_credits = budget.get('credits') if data.get('credit_limited') else credits
    rows=['## HORIZON JAPAN // MISSION CONTROL  運行管制']
    if inventory['current_run']:
        estimate='~' if inventory.get('estimated') else ''
        rows.append(f"**SAVED INVENTORY · {inventory['super_wheelspins']:,}{estimate} SW · {inventory['wheelspins']:,} WS**")
        if inventory.get('estimated'):
            rows.append(f"Home {inventory['actual_super_wheelspins_at_sync']:,} SW + {inventory['verified_rewards_after_sync']:,} verified rewards · sync {discord_time(inventory.get('observed_at'))}")
        else:
            rows.append(f"Home verified · read {discord_time(inventory.get('observed_at'))}")
        correction=inventory.get('hybrid_correction') or {}
        if type(correction.get('delta')) is int and correction['delta']:
            rows.append(f"Last Home correction **{correction['delta']:+,} SW**")
    else: rows.append('**SAVED INVENTORY · SW / WS awaiting current-run read**')
    stage=data.get('stage') or data.get('phase','—'); state='RUNNING' if data.get('active') else 'STOPPED'
    state_line=f'**{state} · {stage}**'
    if data.get('active') and stage!='farm_drive' and numeric(data.get('stage_age_seconds')):
        state_line+=f" · {duration(data['stage_age_seconds'])}"
    progress=data.get('last_confirmed_progress') or {}
    if numeric(progress.get('age_seconds')) and numeric(progress.get('delta')):
        unit='SW' if progress.get('kind')=='wheelspin' else 'SP'
        state_line+=f" · last +{progress['delta']:g} {unit} {discord_time(progress.get('at'))}"
    rows.append(state_line)
    cleanup=a.get('garage_cleanup') or {}; mad=data.get('mad_mike_inventory') or {}
    if cleanup.get('active') or cleanup.get('removed'):
        left=0 if mad.get('actual_zero') else mad.get('remaining',0)
        prefix='' if mad.get('actual_zero') else '≤'
        recent=cleanup.get('recent_removed_at') or []
        try:
            from datetime import datetime
            per_min=((len(recent)-1)*60 /
                     (datetime.fromisoformat(recent[-1])-datetime.fromisoformat(recent[0])).total_seconds()
                     if len(recent)>1 else None)
        except (TypeError,ValueError,ZeroDivisionError): per_min=None
        cleanup_state='RUNNING' if cleanup.get('active') else 'COMPLETE'
        rows.append(f"**MAD MIKE CLEANUP · {cleanup_state}**")
        rows.append(f"**{mad.get('removed',cleanup.get('removed',0)):,} removed · {prefix}{left:,} left** · "
                    f"{mad.get('bought',0):,} bought / {mad.get('processed',0):,} processed"+
                    (f" · {per_min:.1f}/min" if numeric(per_min) else ''))
        if mad.get('reconciled_removed',0):
            rows.append(f"Removal count: {mad.get('confirmed_removed',0):,} logged + "
                        f"{mad['reconciled_removed']:,} reconciled when the garage reached zero")
    if stage=='farm_drive' and data.get('farm_event'):
        timer=data['farm_event'].get('timer','').removeprefix('Farming SP — ').replace('. SP checked after exit.','')
        if timer: rows.append('**CLOCK: '+timer+'**')
    output=f'+{earned:,} SW' if data.get('credit_limited') else f"+{earned:,} / {data.get('target',0):,} SW"
    rows += [
        f"\n**NEW {output}** · cars {bought:,} bought / {data.get('unprocessed',0):,} pending",
        f"**SP {value(data.get('sp'))}/999** · batch {value(data.get('batch_completed'))}/{value(data.get('batch_limit'))} · {data.get('farms',0)} farm runs",
        f"**SW/h {fmt(op.get('sw_active_hour'))} active / {fmt(op.get('sw_wall_hour'))} wall**",
        f"**Cars/h {fmt(op.get('farm_capacity'))} farm / {fmt(op.get('conversion_capacity'))} conversion** · {fmt(op.get('retained_sp_hour'))} SP/h",
        f"Limit: **{op.get('bottleneck','MEASURING')}** · gap {fmt(op.get('imbalance_percent'),'%')}",
        f"\n**P50 {fmt(q.get('p50'),'s')} · P90 {fmt(q.get('p90'),'s')} · P99 {fmt(q.get('p99'),'s')}** · n={q.get('n',0)}"+(' (P99=max)' if 0<q.get('n',0)<100 else '')]
    if numeric(op.get('current_system_active_hour')):
        rows.append(f"Current worker: **{fmt(op['current_system_active_hour'])} SW/h** · +{op.get('current_system_rewards',0)} SW / {duration(op.get('current_system_active_seconds'))} active · capacity gap {fmt(op.get('system_capacity_gap'),' SW/h')}")
    boundaries=op.get('boundary_metrics') or {}
    measured=[(name,values) for name,values in boundaries.items() if numeric((values or {}).get('p50'))]
    if measured:
        labels={'inventory_sync':'inventory','credit_check':'credit','sp_read':'SP read','farm_to_collection':'farm→cars'}
        rows.append('Boundary P50: '+' · '.join(f"{labels.get(name,name)} {fmt(values.get('p50'),'s')}" for name,values in measured))
    stages=op.get('stage_percentiles') or {}
    if any(numeric((v or {}).get('p50')) for v in stages.values()):
        rows.append('P50: '+' · '.join(f"{label} {fmt((stages.get(key) or {}).get('p50'),'s')}" for key,label in [('buy','buy'),('choose','choose'),('open_mastery','open'),('mastery','mastery'),('return','return')]))
    comparison=op.get('cycle_comparison') or {}; current=comparison.get('current') or {}; previous=comparison.get('previous') or {}; delta=comparison.get('percent_delta') or {}
    if current.get('n',0)>0 and previous.get('n',0)>0 and all(numeric(delta.get(k)) for k in ('p50','p90')):
        rows.append(f"Δ {current['n']} vs {previous['n']} cars: P50 **{delta['p50']:+.1f}%** · P90 **{delta['p90']:+.1f}%**")
    tax=op.get('forza_tax_coverage') or {}; tax_value=op.get('forza_tax_percent_estimated')
    tax_label=f'≈{fmt(tax_value,"%")}' if numeric(tax_value) and tax.get('n',0)>0 else '—'
    rows += [f"**Zero retries {fmt(op.get('first_pass_yield'),'%')}** ({op.get('first_pass_samples',0)} cars) · crashes {a.get('crashes',source.get('crashes',0))}",
             f"Forza tax **{tax_label}** residual · {tax.get('n',0)}/{tax.get('total',0)} cars"]
    if data.get('credit_limited'):
        resource=f"\n**CR {money(report_credits)} · ≈{value(budget.get('affordable_new_cars'))} more cars**"
        if budget.get('observed_at'): resource+=f" · read {discord_time(budget['observed_at'])}"
        if numeric(budget.get('committed_credits')) and budget['committed_credits']>0: resource+=f" · {money(budget['committed_credits'])} CR committed"
    else:
        margin=f'{(credits-cost)/1e6:+,.2f}M' if numeric(credits) and numeric(cost) else '—'
        resource=f"\n**CR {money(credits)} · {money(cost)} required · {margin} margin**"
    rows += [resource,f"Spent: **{earned*21:,} SP · {money(bought*95000)} CR**"]
    refill=data.get('refill_status') or {}
    if refill:
        detail=f"Refill: {value(refill.get('before_sp'))} → {value(refill.get('target_sp'))} SP · headroom {value(refill.get('headroom_sp'))} at start"
        if numeric(refill.get('planned_drive_seconds')): detail+=f" · planned {duration(refill['planned_drive_seconds'])} (est.)"
        rows.append(detail)
    if numeric(a.get('eta_seconds')) and numeric(a.get('eta_upper_seconds')):
        rows.append(f"**FINISH {projected_time(data.get('timestamp'),a['eta_seconds'])} to {projected_time(data.get('timestamp'),a['eta_upper_seconds'])} · ≈{a.get('farms_remaining','?')} farm runs**")
    trial=data.get('farm_trial') or {}
    if trial.get('status')=='active': rows.append(f"**MINI V2 TRIAL:** +{max(0,earned-trial.get('start_rewards',earned))} / {trial.get('reward_limit',100)} SW")
    speed=data.get('speed_trial') or {}
    if speed.get('status')=='active' and speed.get('deployment_at') and numeric(speed.get('actual_start_rewards')):
        count=max(0,earned-speed['actual_start_rewards']);limit=speed.get('verified_new_rewards',100)
        if numeric(limit) and limit>0: rows.append(f"**OPTIMIZER TRIAL:** +{min(count,limit):g} / {limit:g} SW · {speed.get('actual_start_total','?')} → {speed.get('target_total','?')} total"+(' · review due' if count>=limit else ''))
    warnings=[]; recovery=data.get('unresolved_recovery') or {}
    if recovery:
        label='RETRY / RECOVERY' if data.get('active') else 'UNRESOLVED / STOPPED'
        warnings.append(f"**{label}: {recovery.get('cause','unclassified')} · {duration(recovery.get('wall_seconds'))} wall**")
        if recovery.get('message'): warnings.append(recovery['message'])
    if data.get('active') and data.get('game')=='closed': warnings.append('Game closed; recovery required.')
    if 'waiting' in str(data.get('sync','')).casefold(): warnings.append('Waiting for full game sync.')
    if not numeric(report_credits): warnings.append('Credits unverified.')
    elif not data.get('credit_limited') and numeric(cost) and credits<cost: warnings.append(f'Credit shortfall: {money(cost-credits)} CR.')
    if warnings: rows+=['\n**ATTENTION**']+warnings
    rows.append(f"\nLv {account.get('level','?')} · Prestige {account.get('prestige','?')} · updated {discord_time(data.get('timestamp'),'F')} ({discord_time(data.get('timestamp'))})")
    return '\n'.join(rows)
