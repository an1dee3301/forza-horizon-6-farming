"""Three curated Discord boards; live summary and a separate garage image."""
import io
import textwrap
from datetime import datetime

from .report_charts import timed, value_axis, trend_axis
from .report_theme import BG, FG, GREEN, RED, AMBER, CYAN, MUTED, GRID, BORDER
from .operations_metrics import numeric, percentiles, fmt
from .report_plotting import (farm_duration, percentile_comparison, cycle_run_chart,
                             numbered_series, observed_timeline, forza_tax_chart,
                             refill_output_chart, farm_rate_chart)


TITLES = ('MISSION & CONVERSION', 'SP FARM', 'RELIABILITY')
FILENAMES = tuple(f'board_{i+1}.png' for i in range(3))


def summary_lines(data):
    """Shared live KPI definitions for the board header and Discord summary."""
    matched = bool(data.get('goal_id')) and (data.get('charts') or {}).get('goal_id') == data.get('goal_id')
    op = (data.get('analytics') or {}).get('operations', {}) if matched else {}
    q = op.get('cycle_percentiles', {})
    money = lambda v: f'{v/1e6:,.1f}M' if numeric(v) else 'Unknown'
    cost = (data.get('analytics') or {}).get('credits_required')
    progress_line=inventory_heading(data)[0]
    lines=[
        progress_line,
        f"{fmt(op.get('sw_active_hour'))} SW/h ACTIVE · {fmt(op.get('sw_wall_hour'))} SW/h WALL",
        f"SP FARM {fmt(op.get('farm_capacity'))} cars/h · CONVERSION {fmt(op.get('conversion_capacity'))} cars/h",
        f"BOTTLENECK: {op.get('bottleneck','MEASURING')} · IMBALANCE {fmt(op.get('imbalance_percent'),'%')}",
        f"P50 {fmt(q.get('p50'),'s')} · P90 {fmt(q.get('p90'),'s')} · P99 {fmt(q.get('p99'),'s')} · CLEAN CARS {fmt(op.get('first_pass_yield'),'%')}",
        f"CREDITS {money((data.get('account') or {}).get('credits'))} CR · " +
        (f"≈{(data.get('credit_budget_estimate') or {}).get('affordable_new_cars','?')} MORE CARS AFFORDABLE"
         if data.get('credit_limited') else f"{money(cost)} REQUIRED (EST.)"),
    ]
    if numeric(op.get('current_system_active_hour')):
        lines.insert(2,f"CURRENT WORKER {fmt(op['current_system_active_hour'])} SW/h · CAPACITY GAP {fmt(op.get('system_capacity_gap'),' SW/h')}")
    cleanup=(data.get('analytics') or {}).get('garage_cleanup') or {}
    mad=data.get('mad_mike_inventory') or {}
    if mad:
        left=0 if mad.get('actual_zero') else mad.get('remaining',0)
        prefix='' if mad.get('actual_zero') else '≤'
        stock_line=(f"MAD MIKE {prefix}{left:,} LEFT · {mad.get('bought',0):,} BOUGHT · "
                    f"{mad.get('processed',0):,} PROCESSED · {mad.get('removed',0):,} REMOVED")
        if cleanup.get('active'):
            lines.insert(1, stock_line)
        else:
            lines.append(stock_line)
    if cleanup.get('active') or cleanup.get('removed'):
        recent=cleanup.get('recent_removed_at') or []
        try:
            rate=(len(recent)-1)*3600/(datetime.fromisoformat(recent[-1])-datetime.fromisoformat(recent[0])).total_seconds() if len(recent)>1 else None
        except (TypeError,ValueError,ZeroDivisionError): rate=None
        if not numeric(rate):
            elapsed=cleanup.get('elapsed_seconds')
            if cleanup.get('active') and cleanup.get('started_at'):
                try:
                    elapsed=max(0,(datetime.fromisoformat(data['timestamp'])-
                                   datetime.fromisoformat(cleanup['started_at'])).total_seconds())
                except (KeyError,TypeError,ValueError): pass
            baseline=cleanup.get('session_start_removed',0)
            count=max(0,cleanup.get('removed',0)-baseline)
            rate=count*3600/elapsed if numeric(elapsed) and elapsed>0 else None
        cleanup_line=(f"GARAGE CLEANUP {cleanup.get('removed',0):,} REMOVED"+
                      (f" · {rate:,.0f} CARS/h" if numeric(rate) else '')+
                      (' · RUNNING' if cleanup.get('active') else ' · COMPLETE'))
        if cleanup.get('active'):
            lines.insert(2, cleanup_line)
        else:
            lines.append(cleanup_line)
    return lines


def inventory_heading(data):
    """Snapshot-validated native inventory; mission production cannot become stock."""
    from .inventory import inventory_summary
    inventory=inventory_summary(data)
    if not inventory.get('current_run'):
        return ('INVENTORY · SW — · WS —', 'Awaiting a verified My Horizon inventory read in this worker run')
    count=lambda value:f'{value:,}' if type(value) is int and value>=0 else '—'
    sw,ws=inventory.get('super_wheelspins'),inventory.get('wheelspins')
    estimate='~' if inventory.get('estimated') else ''
    heading=f'SAVED INVENTORY · {count(sw)}{estimate} SW · {count(ws)} WS'
    age=inventory.get('age_seconds')
    age=f'{age/60:.1f}m ago' if numeric(age) and age>=0 else 'age unknown'
    if inventory.get('estimated'):
        detail=(f"Home {count(inventory.get('actual_super_wheelspins_at_sync'))} SW + "
                f"{count(inventory.get('verified_rewards_after_sync'))} verified rewards · sync {age}")
    else:detail=f"Home verified {inventory.get('observed_at') or 'time unavailable'} · {age}"
    correction=inventory.get('hybrid_correction') or {}
    if type(correction.get('delta')) is int and correction['delta']:
        detail+=f" · last correction {correction['delta']:+,} SW"
    return heading,detail


def cycle_comparison(cycles):
    """Consecutive 20-car periods; short warm-up is never a full-period comparison."""
    current=percentiles(r.get('elapsed_seconds') for r in cycles[-20:])
    previous=percentiles(r.get('elapsed_seconds') for r in cycles[-40:-20])
    comparable=current['n']==previous['n']==20
    delta={k:100*(current[k]/previous[k]-1) if comparable and previous[k]>0 else None
           for k in ('p50','p90')}
    return dict(current=current,previous=previous,percent_delta=delta)


def report_context(data, op, cycles, page):
    """Decision-oriented headline, grounded in the displayed measurements."""
    if page==0:
        bottleneck=op.get('bottleneck')
        if bottleneck in {'SP FARM','CONVERSION'}:
            name='SP farming' if bottleneck=='SP FARM' else 'Conversion'
            return f"Bottleneck: {name} · farm + conversion capacity {fmt(op.get('combined_capacity'))} SW/h (estimated)"
        return 'Measuring farm and car speed; capacity comparison is not ready yet.'
    if page==1:
        return farm_header(op,len((data.get('charts') or {}).get('farms',[])))
    cleanup=(data.get('analytics') or {}).get('garage_cleanup') or {}
    cleanup_line=(f" · garage cleanup {cleanup.get('removed',0):,} removed"+
                  (' (running)' if cleanup.get('active') else '')) if cleanup.get('removed') or cleanup.get('active') else ''
    coverage=op.get('forza_tax_coverage') or {}
    current=(f" · current worker {fmt(op.get('current_system_active_hour'))} SW/h"
             if numeric(op.get('current_system_active_hour')) else '')
    return (f"First-pass yield {fmt(op.get('first_pass_yield'),'%')} · {op.get('first_pass_samples',0)} instrumented cars · "
            f"Forza residual coverage {coverage.get('n',0)}/{coverage.get('total',len(cycles))} cars"+current+cleanup_line)


def comparison_statement(ax, comparison):
    ax.set_axis_off()
    current,previous=comparison['current'],comparison['previous']
    for x,label in [(.0,'METRIC'),(.33,'LAST 20'),(.58,'PREVIOUS 20'),(.83,'CHANGE')]:
        ax.text(x,.86,label,transform=ax.transAxes,color=MUTED,fontsize=12)
    for y,key in [(.62,'p50'),(.39,'p90')]:
        change=comparison['percent_delta'][key]
        for x,text,color in [(0,key.upper(),FG),(.33,fmt(current[key],'s'),FG),
                             (.58,fmt(previous[key],'s'),MUTED),(.83,f'{change:+.1f}%' if numeric(change) else '—',
                              GREEN if numeric(change) and change<0 else RED if numeric(change) and change>0 else MUTED)]:
            ax.text(x,y,text,transform=ax.transAxes,color=color,fontsize=19)
    ax.text(0,.08,f"n={current['n']} vs n={previous['n']} · lower is faster\n"
            'Change shown only after 20 cars in both groups; it does not prove the cause.',
            transform=ax.transAxes,color=MUTED,fontsize=12)


def capital_statement(ax, data):
    ax.set_axis_off()
    a=data.get('analytics') or {}; budget=data.get('credit_budget_estimate') or {}
    account=data.get('account') or {}
    money=lambda v:f'{v/1e6:,.2f}M CR' if numeric(v) else 'Unobserved'
    rows=[('Credits',money(account.get('credits')),'OBSERVED')]
    if data.get('credit_limited'):
        count=budget.get('affordable_new_cars')
        rows.append(('Extra cars affordable',f'{count:,}' if type(count) is int else 'Unestimated','ESTIMATE'))
        pending=budget.get('pending_cars',data.get('unprocessed'))
        rows.append(('Cars waiting for mastery',f'{pending:,}' if type(pending) is int else 'Unobserved','COUNT'))
    else:
        rows.append(('Remaining Mazda budget',money(a.get('credits_required')),'ESTIMATE'))
        value=account.get('credits'); cost=a.get('credits_required')
        rows.append(('Credit margin',money(value-cost) if numeric(value) and numeric(cost) else 'Unestimated','ESTIMATE'))
    bought=data.get('bought')
    rows.append(('Cars purchased this mission',f'{bought:,}' if type(bought) is int else 'Unobserved','COUNT'))
    rows.append(('Car cost',money(bought*95000) if type(bought) is int else 'Unobserved','COUNT × PRICE'))
    for y,(label,value,basis) in zip([.84,.67,.50,.33,.16],rows):
        ax.text(0,y,label,transform=ax.transAxes,color=FG,fontsize=15)
        ax.text(.61,y,value,transform=ax.transAxes,color=FG,fontsize=16,ha='right')
        ax.text(.98,y,basis,transform=ax.transAxes,color=MUTED,fontsize=11,ha='right')
    ax.text(0,-.16,'Car cost = purchases × 95,000 CR. Other credit gains and spending are not tracked here.',
            transform=ax.transAxes,color=MUTED,fontsize=12,va='top')


def account_summary(data):
    a = data.get('account') or {}
    age = lambda stamp: fmt(age_minutes(stamp, data.get('timestamp')), 'm ago') if stamp else 'age unknown'
    return (f"SP {data.get('sp','?')} ({age(data.get('sp_observed_at'))}) · "
            f"Level {a.get('level','?')} ({age(a.get('level_observed_at'))}) · "
            f"Prestige {a.get('prestige','?')} · "
            f"Credits read {age(a.get('observed_at'))}")


def age_minutes(timestamp, reference):
    try:
        stamp, now = datetime.fromisoformat(timestamp), datetime.fromisoformat(reference)
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        if now.tzinfo is None:
            now = now.astimezone()
        return max(0, (now-stamp).total_seconds()/60)
    except (ValueError, TypeError):
        return None


def recent_farm_waste_header(op):
    """Prefer the explicitly identified recent Mega cohort, not older mission gaps."""
    count = lambda value: value if type(value) is int and value >= 0 else 0
    total = count(op.get('recent_cap_loss_total_runs'))
    if (op.get('recent_cap_loss_share_code') != '155439962' or not total or
            not op.get('recent_cap_loss_cohort_start_id')):
        return None
    samples = count(op.get('recent_cap_loss_rate_samples'))
    seconds = op.get('recent_cap_loss_rate_seconds')
    rate = op.get('recent_cap_loss_sp_farm_hour_estimated')
    cars = op.get('recent_cap_loss_mazda_farm_hour_estimated')
    unknown = count(op.get('recent_cap_loss_unknown_capped_runs'))
    available = (0 < samples <= total and numeric(seconds) and seconds > 0 and not unknown and
                 numeric(rate) and rate >= 0 and numeric(cars) and cars >= 0)
    waste = f'{rate:,.1f} SP/h ≈ {cars:,.2f} Mazda/h' if available else 'unavailable'
    if unknown:
        waste += f" · {unknown:,} capped {'run' if unknown == 1 else 'runs'} unestimated"
    timed = (f'Timed {samples:,}/{total:,} runs · {seconds/3600:.2f} farm h'
             if type(op.get('recent_cap_loss_rate_samples')) is int and
             numeric(seconds) and seconds >= 0 else 'Timed coverage unavailable')
    partial = op.get('recent_cap_loss_partial_timing_runs')
    partial = f'{partial:,} partial excluded' if type(partial) is int and partial >= 0 else 'partial timing unknown'
    loss = op.get('recent_cap_loss_sp_estimated')
    loss_samples = count(op.get('recent_cap_loss_samples'))
    known = (f'known cap loss {loss:,.1f} SP across {loss_samples:,} runs'
             if numeric(loss) and loss >= 0 and loss_samples else 'known cap loss unavailable')
    mission_unknown = count(op.get('cap_loss_unknown_capped_runs'))
    historical = f' · mission: {mission_unknown:,} capped unestimated' if mission_unknown else ''
    return (f'MEGA RECENT COHORT · SP WASTE/FARM HOUR (EST.): {waste}\n'
            f'{timed} · {partial} · {known}{historical}')


def farm_header(op, completed_runs):
    """One farm waste metric; estimated loss and its timed cohort stay explicit."""
    recent = recent_farm_waste_header(op)
    if recent is not None:
        return recent
    count = lambda value: value if type(value) is int and value >= 0 else 0
    loss_samples = count(op.get('cap_loss_samples'))
    loss = op.get('cap_loss_sp_estimated')
    total = f'{loss:,.1f} SP' if numeric(loss) and loss >= 0 and loss_samples else 'unavailable'
    samples = count(op.get('cap_loss_rate_samples'))
    seconds = op.get('cap_loss_rate_seconds')
    rate = op.get('cap_loss_sp_farm_hour_estimated')
    cars = op.get('cap_loss_mazda_farm_hour_estimated')
    available = (samples > 0 and numeric(seconds) and seconds > 0 and
                 numeric(rate) and rate >= 0 and numeric(cars) and cars >= 0)
    waste = f'{rate:,.1f} SP/h ≈ {cars:,.1f} Mazda/h' if available else 'unavailable'
    total_runs = count(op.get('cap_loss_rate_total_runs', completed_runs))
    coverage = (f'{samples:,}/{total_runs:,} runs, {seconds/3600:,.1f}h'
                if type(op.get('cap_loss_rate_samples')) is int and
                numeric(seconds) and seconds >= 0 else 'unavailable')
    retained = op.get('retained_sp_hour')
    retained = f'{retained:,.1f} SP/h' if numeric(retained) and retained >= 0 else 'unavailable'
    unknown_capped = count(op.get('cap_loss_unknown_capped_runs'))
    if unknown_capped:
        return (f'SP WASTE/FARM HOUR (EST.): unavailable · {unknown_capped:,} capped runs lack supported estimates\n'
                f'Rate coverage {coverage} · retained {retained}')
    return (f'SP WASTE/FARM HOUR (EST.): {waste} · total {total} ({loss_samples:,}/{completed_runs:,} runs) · '
            f'rate coverage {coverage} · retained {retained}')


def build_boards(data, game_image=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.ticker import MaxNLocator

    source = data.get('charts') or {}
    matched = bool(data.get('goal_id')) and source.get('goal_id') == data.get('goal_id')
    if not matched:
        source = {}
    op = data.get('analytics', {}).get('operations', {}) if matched else {}
    cycles = [r for r in source.get('cycles', []) if numeric(r.get('elapsed_seconds')) and r['elapsed_seconds'] > 0]
    farms, refills = source.get('farms', []), source.get('refills', [])
    recent = cycles[-80:]
    target = data.get('cycle_target_seconds', 30)
    cycle_offset=source.get('cycle_offset',0)
    if type(cycle_offset) is not int or cycle_offset<0: cycle_offset=0
    progress_times=timed(source.get('progress',[]),'earned','at')
    time_origin=progress_times[0][0] if progress_times else None
    boards = []
    from .account_header import latest_strip
    strip = latest_strip(game_image,data)

    def board(index, subtitle, count):
        from matplotlib.lines import Line2D
        tall = count in {8, 9}
        fig = Figure(figsize=(24, 32 if tall or count == 6 else 21 if count == 4 else 25), dpi=100, facecolor=BG)
        FigureCanvasAgg(fig)
        grid = fig.add_gridspec(5 if tall else 2 if count == 4 else 3, 2)
        if count == 9:
            axes = [fig.add_subplot(grid[0,0]), fig.add_subplot(grid[0,1]),
                    fig.add_subplot(grid[1,:])]
            axes += [fig.add_subplot(grid[row,col]) for row in range(2,5) for col in range(2)]
        elif count == 8:
            axes = [fig.add_subplot(grid[0,0]), fig.add_subplot(grid[0,1]),
                    fig.add_subplot(grid[1,:])]
            axes += [fig.add_subplot(grid[row,col]) for row in range(2,4) for col in range(2)]
            axes.append(fig.add_subplot(grid[4,:]))
        elif count == 5:
            axes = [fig.add_subplot(grid[row,col]) for row in range(2) for col in range(2)]
            axes.append(fig.add_subplot(grid[2,:]))
        elif count == 4:
            axes = [fig.add_subplot(grid[row,col]) for row in range(2) for col in range(2)]
        else:
            axes = [fig.add_subplot(grid[row,col]) for row in range(3) for col in range(2)]
        fig.subplots_adjust(left=.12, right=.97, top=.66, bottom=.12 if count==6 else .17 if count==4 else .14 if count==5 else .09,
                            hspace=.55 if count == 4 else .65 if count == 5 else .8, wspace=.44)
        fig.text(.045, .979, f'FH6 // {index+1}/3  {TITLES[index]}', color=GREEN, fontsize=30, va='top')
        fig.text(.53,.958,'CURRENT RUN · LIVE MEASUREMENTS',color=MUTED,fontsize=14,va='top')
        fig.text(.53,.942,'Snapshot '+data.get('timestamp','unavailable'),color=MUTED,fontsize=13,va='top')
        if strip:
            from PIL import Image
            photo = fig.add_axes((.045, .915, .47, .043), label='account_strip')
            photo.imshow(Image.open(io.BytesIO(strip[0]))); photo.axis('off')
            fig.text(.53,.923,'ACCOUNT CAPTURE · '+strip[1],color=MUTED,fontsize=13,va='top')
        inventory_title,inventory_read=inventory_heading(data)
        fig.text(.045,.901,inventory_title,color=FG,fontsize=29,va='top')
        fig.text(.045,.878,inventory_read,color=MUTED,fontsize=13,va='top')
        for y,line in zip((.854,.832,.810,.788,.766),summary_lines(data)[1:]):
            fig.text(.045,y,line,color=FG,fontsize=23,va='top')
        fig.text(.045,.740,
                 f"+{data.get('earned',0):,} NEW SW · {data.get('bought',0):,} BOUGHT · "
                 f"{data.get('unprocessed',0)} PENDING · SP {data.get('sp','?')}/999 · "
                 f"FORZA TAX ≈{fmt(op.get('forza_tax_percent_estimated'),'%')} · "
                 f"{op.get('first_pass_samples',0)} cars tracked for retries",
                 color=MUTED,fontsize=16,va='top')
        fig.text(.045, .714, subtitle, color=MUTED, fontsize=15,va='top',linespacing=1.3)
        fig.text(.045, .02, 'CURRENT MISSION · P50/P90/P99: last 20 cars (P99 = maximum) · Clean cars: zero retries · Rates: newly earned SW only\n'
                 'Forza tax = observed residual; polling/pacing excluded · Causal game share unmeasured · Cycle gaps outside recorder excluded\n'
                 + account_summary(data) + '\n' + data.get('timestamp','') + ' | Mission ' + data.get('goal_id','unknown'),
                 color=MUTED, fontsize=15, va='bottom', linespacing=1.4)
        for ax in axes:
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=15)
            ax.xaxis.label.set(color=MUTED, size=16)
            ax.yaxis.label.set(color=MUTED, size=16)
            ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            ax.grid(axis='y', color=GRID, linewidth=.8)
            ax.set_axisbelow(True)
        boards.append(fig)
        return axes

    def title(ax, text):
        ax.set_title(text, loc='left', color=FG, fontsize=20, pad=17)

    def empty(ax, note='No verified measurements for this panel yet'):
        ax.text(.5, .5, textwrap.fill(note, 40), transform=ax.transAxes,
                color=MUTED, fontsize=18, ha='center', va='center')
        ax.set_xticks([]); ax.set_yticks([])

    def legend(ax):
        ax.legend(facecolor=BG, edgecolor=BORDER, labelcolor=FG, fontsize=14)

    def bars(ax, values, label, color=GREEN, target_value=None):
        valid = [(str(k).replace('_', ' '), v) for k,v in values.items() if numeric(v) and v>=0]
        if not valid:
            empty(ax); return
        valid.sort(key=lambda item: item[1], reverse=True)
        names, vals = zip(*valid)
        ax.barh(range(len(names)), vals, color=color)
        ax.set_yticks(range(len(names)),[textwrap.fill(n, 23) for n in names])
        ax.invert_yaxis()
        ax.grid(False); ax.grid(axis='x', color=GRID, linewidth=.8)
        ax.set_xlabel(label)
        value_axis(ax, vals, horizontal=True, target=target_value)
        for i,v in enumerate(vals):
            ax.annotate(f'{v:,.1f}', (v,i), xytext=(-5 if v > max(vals)*.2 else 5,0),
                        textcoords='offset points', ha='right' if v > max(vals)*.2 else 'left',
                        va='center', fontsize=14, color=BG if v > max(vals)*.2 else FG)

    def timeline(ax, rows, field, stamp, ylabel, divisor=1, addition=0, limit=None):
        observed_timeline(ax,rows,field,stamp,divisor=divisor,addition=addition,
                          target=limit,ylabel=ylabel,origin=time_origin)

    a = board(0, report_context(data,op,cycles,0), 8)
    title(a[0], '01 · Total saved Super Wheelspins')
    samples=source.get('inventory',[])
    for field,label,color in [('super_wheelspins','Super Wheelspins',GREEN)]:
        points=timed(samples,field,'observed_at')
        if points:
            origin=time_origin if time_origin is not None else points[0][0]
            a[0].plot([(stamp-origin)/3600 for stamp,_ in points],[v for _,v in points],
                      marker='o',markersize=4,linestyle=':',color=color,label=label)
    live=source.get('inventory_hybrid') or {}
    live_points=timed([live],'super_wheelspins','observed_at') if live.get('verified_rewards_after_sync',0)>0 else []
    if live_points:
        origin=time_origin if time_origin is not None else live_points[0][0]
        a[0].scatter([(live_points[-1][0]-origin)/3600],[live_points[-1][1]],marker='x',s=70,
                     linewidths=2,color=AMBER,label='Live hybrid estimate',zorder=5)
    if a[0].lines:
        trend_axis(a[0],[v for line in a[0].lines for v in line.get_ydata()]
                   +[v for _,v in live_points]);legend(a[0])
        a[0].set_xlabel('Hours; dots = Home readings · × = verified rewards since Home')
        a[0].set_ylabel('Saved inventory')
    else:empty(a[0],'Awaiting actual saved-spin readings')
    title(a[1], '02 · Capacity and sequential throughput')
    bars(a[1],{k:op.get(v) for k,v in [('SP farm','farm_capacity'),('Conversion','conversion_capacity'),('Sequential combined','combined_capacity')]},'Cars / hour; same game performs stages sequentially')
    rate=op.get('rate_coverage') or {}
    farm_n=rate.get('farm_n',op.get('farm_rate_samples',0))
    conversion_n=rate.get('conversion_n',op.get('conversion_rate_samples',0))
    farm_profile=rate.get('farm_profile') or 'profile unrecorded'
    farm_hours=rate.get('farm_seconds')
    coverage=(f"Farm: {farm_n} timed runs ({farm_profile})"
              + (f" / {farm_hours/3600:.2f}h" if numeric(farm_hours) else '')
              +f" · Conversion: {conversion_n} cars")
    a[1].text(0,-.39,coverage+'\nCombined = 1 / (1/farm + 1/conversion); estimated capacity, not observed SW/h',
              transform=a[1].transAxes,color=MUTED,fontsize=12,va='top')
    title(a[2], '03 · Buy → mastery → return | last 80')
    if cycles: cycle_run_chart(a[2],cycles,target=target,start=cycle_offset+1)
    else: empty(a[2])
    title(a[3], '04 · Rolling 20 car P50 / P90')
    windows=[percentiles(r['elapsed_seconds'] for r in cycles[i-19:i+1]) for i in range(19,len(cycles))]
    if windows:
        x=range(cycle_offset+20,cycle_offset+len(cycles)+1)
        for key,color in [('p50',GREEN),('p90',AMBER)]:
            a[3].plot(x,[q[key] for q in windows],color=color,label=key.upper(),linewidth=1.5)
        trend_axis(a[3],[q[k] for q in windows for k in ('p50','p90')])
        legend(a[3])
        a[3].set_xlabel('Completed car; every point uses 20 cars')
        a[3].set_ylabel('Recorded seconds; slow cars retained')
        comparison=cycle_comparison(cycles)
        delta=comparison['percent_delta']
        if all(numeric(delta[k]) for k in ('p50','p90')):
            a[3].text(0,-.36,f"Latest 20 vs previous 20: P50 {delta['p50']:+.1f}% · P90 {delta['p90']:+.1f}% (lower is faster)",
                      transform=a[3].transAxes,color=MUTED,fontsize=12,va='top')
    else: empty(a[3],'Needs 20 completed cars')
    title(a[4], '05 · Active time by activity')
    bars(a[4],{k:v/3600 for k,v in source.get('seconds',{}).items() if numeric(v)},
         'Recorded active hours; offline time excluded')

    for i,(key,label) in enumerate([('choose','Choose newest car'),('mastery','Claim mastery path'),('return','Return to collection')]):
        title(a[i+5],f'{i+6:02d} · {label} | last 80')
        numbered_series(a[i+5],[r.get('steps',{}).get(key) for r in recent],
                        'Recorded stage seconds',start=cycle_offset+len(cycles)-len(recent)+1,focus=True)

    a = board(1, report_context(data,op,cycles,1), 6)
    title(a[0], '09 · Verified SP balance')
    timeline(a[0],source.get('progress',[]),'sp','sp_at','Skill points',limit=999)
    active_profile=data.get('active_farm_share_code') or (data.get('farm_event') or {}).get('share_code') or rate.get('farm_share_code')
    farm_duration(a[1],farms,share_code=active_profile,number=10)
    title(a[2], '11 · Stage P50 / P90 / P99 | last 20')
    percentile_comparison(a[2],op.get('stage_percentiles',{}),'Seconds per recorded stage')
    refill_output_chart(a[3],refills,number=12)

    # Only the current consecutive farm profile; no old Mini/Mega mixing.
    cutoff=max((i+1 for i,r in enumerate(farms) if r.get('share_code') and r.get('share_code')!=active_profile),default=0)
    farm_rows=[r for r in farms[cutoff:] if r.get('share_code')==active_profile][-20:]
    title(a[4], '13 · SP kept per run | current challenge')
    a[4].set_xlabel('Recent run; blue = planned top-up, amber = partial timing')
    for i,r in enumerate(farm_rows,1):
        gain=r.get('gained_sp');duration=r.get('active_seconds')
        color=AMBER if r.get('partial_timing') is not False else CYAN if r.get('run_type')=='intentional_top_up' else GREEN
        if numeric(gain) and gain>=0:
            a[4].bar(i,gain,color=color)
            a[4].annotate(f'{gain:g}',(i,gain),xytext=(0,4),textcoords='offset points',ha='center',color=FG,fontsize=11)
    a[4].set_ylabel('Actual retained SP')
    a[4].set_ylim(bottom=0)
    a[4].margins(y=.12)
    farm_rate_chart(a[5],farms,share_code=active_profile,number=14)
    if not farm_rows:
        empty(a[4])

    a = board(2,report_context(data,op,cycles,2),8)
    causes=op.get('failures',{})
    covered=[r for r in cycles if r.get('recovery_tracking_version')==2]
    title(a[0], '15 · Conversion retries / 100 instrumented cars')
    bars(a[0],{k:v.get('per_100_cars') for k,v in causes.items()},
         f"Events / 100 completed instrumented cars; denominator n={op.get('first_pass_samples',0)}",RED)
    title(a[1], '16 · Mission recovery time by cause')
    bars(a[1],{k:v['recovery_seconds']/60 for k,v in causes.items() if numeric(v.get('recovery_seconds'))},'Recorded minutes; includes farm and conversion recovery',RED)
    forza_tax_chart(a[2],cycles,start=cycle_offset+1,number=17)
    title(a[3], '18 · Farm ↔ conversion boundary latency')
    percentile_comparison(a[3],op.get('boundary_metrics') or {},
                          'Seconds per measured boundary; P50 / P90 / P99')
    title(a[4], '19 · Input → usable screen')
    transition_n=op.get('transition_coverage') or {}
    percentile_comparison(a[4],{k:dict(v.get('input_to_usable',{}),total=transition_n.get(k,{}).get('total'))
                               for k,v in op.get('transition_stages',{}).items()},
                          'Seconds; n = usable timing / all transitions; sampled visual proxy')
    title(a[5], '20 · Recovery cost per failure | P50 / P90 / P99')
    percentile_comparison(a[5],{k:v.get('cost',{}) for k,v in causes.items()},
                          'Seconds per measured recovery; missing costs excluded')
    mad=data.get('mad_mike_inventory') or {}
    title(a[6], '21 · Mad Mike totals')
    mad_values=[mad.get('bought'),mad.get('processed'),mad.get('removed'),mad.get('remaining')]
    if any(numeric(value) for value in mad_values):
        names=['Bought','Mastery complete','Removed','Remaining upper bound']
        colors=[CYAN,GREEN,AMBER,RED]
        values=[value if numeric(value) and value>=0 else 0 for value in mad_values]
        a[6].barh(range(4),values,color=colors)
        a[6].set_yticks(range(4),names);a[6].invert_yaxis()
        a[6].set_xlabel('Cars; remaining is bought minus confirmed removals')
        a[6].set_xlim(0,max(1,max(values))*1.08)
        for index,value in enumerate(values):
            a[6].annotate(f'{value:,.0f}',(value,index),xytext=(-7 if value else 5,0),
                          textcoords='offset points',ha='right' if value else 'left',
                          va='center',fontsize=14,color=BG if value else FG,fontweight='bold')
        complete=100*mad.get('removed',0)/mad.get('bought',1) if mad.get('bought',0)>0 else 0
        a[6].text(0,-.25,f"Removed {complete:.1f}% · actual zero requires verified empty filtered grid",
                  transform=a[6].transAxes,color=MUTED,fontsize=12,va='top')
    else:empty(a[6],'No Mad Mike inventory counters recorded')
    title(a[7], '22 · Mad Mike cleanup progress')
    cleanup_rows=source.get('garage_cleanup') or []
    cleanup_points=timed(cleanup_rows,'removed_total','at')
    if cleanup_points and numeric(mad.get('bought')):
        start=cleanup_points[0][0]
        x=[(stamp-start)/60 for stamp,_ in cleanup_points]
        removed_values=[value for _,value in cleanup_points]
        remaining_values=[max(0,mad['bought']-value) for value in removed_values]
        a[7].plot(x,removed_values,color=AMBER,linewidth=2,label='Confirmed removed')
        a[7].plot(x,remaining_values,color=RED,linewidth=2,label='Remaining upper bound')
        a[7].axhline(mad['bought'],color=CYAN,linestyle='--',linewidth=1.2,label=f"Bought total {mad['bought']:,}")
        a[7].set_ylim(0,max(1,mad['bought'])*1.08)
        a[7].set_xlabel('Minutes since first instrumented removal')
        a[7].set_ylabel('Mad Mike cars')
        legend(a[7])
    else:empty(a[7],'Cleanup history will appear after a confirmed removal')
    for fig in boards:
        for ax in fig.axes:
            ax.set_xlabel(textwrap.fill(ax.get_xlabel(),60))
            ax.set_ylabel(textwrap.fill(ax.get_ylabel(),42))
    return boards


def render_boards(data, game_image=None):
    output=[]
    for filename,title,fig in zip(FILENAMES,TITLES,build_boards(data,game_image)):
        buffer=io.BytesIO()
        fig.savefig(buffer,format='png',facecolor=BG)
        output.append((filename,buffer.getvalue(),title))
        fig.clear()
    return output
