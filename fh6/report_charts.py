"""Discord plots from measured mission data. Rendering stays in the reporter."""
import io
import textwrap
from datetime import datetime
from statistics import median

from .chart_data import number
from .report_theme import BG, FG, GREEN, RED, AMBER, CYAN, MUTED, GRID, BORDER

HEADROOM = 1.08


def focused_limits(values, *, reference=None, minimum_span=1):
    """User scale: 90% of minimum through 110% of maximum."""
    valid=[float(v) for v in values if number(v)]
    if number(reference): valid.append(float(reference))
    if not valid: return None
    lo,hi=min(valid),max(valid)
    lower=lo-abs(lo)*.10
    upper=hi+abs(hi)*.10
    if upper-lower < minimum_span:
        extra=(minimum_span-(upper-lower))/2
        lower-=extra;upper+=extra
    return max(0,lower) if lo>=0 else lower,upper


def trend_axis(ax, values, *, reference=None, minimum_span=1):
    limits=focused_limits(values,reference=reference,minimum_span=minimum_span)
    if limits is not None:
        ax.set_ylim(*limits)
        ax.ticklabel_format(axis='y',style='plain',useOffset=False)


def value_axis(ax, values, *, horizontal=False, target=None):
    """Target charts end at 108% of target; untargeted charts use data max."""
    if number(target) and target > 0:
        (ax.set_xlim if horizontal else ax.set_ylim)(0, target*HEADROOM)
        return
    values = [v for v in values if number(v)]
    if not values:
        return
    lower, upper = min(0, min(values))*HEADROOM, max(0, max(values))*HEADROOM
    if lower == upper:
        upper = 1  # Keep an all-zero chart usable without inventing a value.
    (ax.set_xlim if horizontal else ax.set_ylim)(lower, upper)


def measured_cycles(data):
    return [r for r in data.get('cycles', [])
            if number(r.get('elapsed_seconds')) and r['elapsed_seconds'] > 0]


def cycle_summary(data, target_seconds=55):
    values = sorted(r['elapsed_seconds'] for r in measured_cycles(data)[-20:])
    if not values:
        return 'No completed cars measured in this mission yet.'
    import math
    return (f'Last {len(values)} cars: median {median(values):.1f}s / '
            f'P90 {values[math.ceil(.9*len(values))-1]:.1f}s\n'
            f'{sum(v < target_seconds for v in values)}/{len(values)} below {target_seconds}s · recorded cycle timer')


def cycle_display(values, target_seconds):
    """Zoom extreme recovery delays out of the plot, never out of statistics."""
    cutoff = max(median(values)*3, target_seconds*2)
    return [v if v <= cutoff else float('nan') for v in values], [
        i for i,v in enumerate(values) if v > cutoff]


def timed(rows, field, timestamp='at'):
    result = []
    for row in rows:
        if not number(row.get(field)):
            continue
        try:
            stamp = datetime.fromisoformat(row[timestamp]).timestamp()
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        result.append((stamp, row[field]))
    # Sort by time only: equal-time observations retain ingestion order instead
    # of being silently reordered by the numeric reading (e.g. a falling SP).
    return sorted(result, key=lambda point: point[0])


def recent_farm_regime(rows, limit=15):
    """Select the latest contiguous explicit profile before any outcome filter."""
    if not rows:
        return [], 'No identified current farm profile'
    code=str(rows[-1].get('share_code','')).replace(' ','')
    if not code.isdigit() or len(code)!=9:
        return [], 'Latest farm profile is unrecorded'
    selected=[]
    for row in reversed(rows):
        if str(row.get('share_code','')).replace(' ','')!=code:
            break
        selected.append(row)
        if len(selected)==limit: break
    return list(reversed(selected)), rows[-1].get('profile_name') or code


def render_charts(data, *, focused=False):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.ticker import MaxNLocator
    from .report_plotting import cycle_run_chart, percentile_comparison

    source = data.get('charts') or {}
    # Reject a stale caller snapshot instead of presenting another mission's samples.
    matched=bool(data.get('goal_id')) and source.get('goal_id')==data.get('goal_id')
    if not matched:
        source = {}
    progress=timed(source.get('progress',[]),'earned')
    time_origin=progress[0][0] if progress else None

    def figure(rows, title):
        fig = Figure(figsize=(16, rows*4.2+1.3), dpi=100, facecolor=BG)
        FigureCanvasAgg(fig)
        axes = fig.subplots(rows, 2).flatten()
        fig.subplots_adjust(left=.14, right=.97, bottom=.10, top=.84 if rows == 2 else .88,
                            wspace=.42, hspace=.55)
        fig.suptitle('FH6 // '+title+(' | ARCHIVED PREVIEW' if data.get('archived_preview') else ''),
                     color=GREEN, fontsize=22, x=.055, ha='left', y=.975)
        from .inventory import inventory_summary
        inventory=inventory_summary(data)
        estimate='~' if inventory.get('estimated') else ''
        tally=(f"Saved inventory: {inventory['super_wheelspins']:,}{estimate} SW · {inventory['wheelspins']:,} WS"
               if inventory['current_run'] else 'Saved inventory: awaiting current-run game reading')
        fig.text(.055, .925, tally+' | '
                 f"Mission {data.get('goal_id', '?')} | {data.get('timestamp', '')}", color=FG, fontsize=11)
        fig.text(.055, .022, 'Current mission measurements only. Missing data stays empty. '
                 'Newly earned mission output is separate from actual saved inventory.', color=MUTED, fontsize=11)
        for ax in axes:
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=10)
            ax.xaxis.label.set_color(MUTED)
            ax.yaxis.label.set_color(MUTED)
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            ax.grid(axis='y', color=GRID, linewidth=.6)
            ax.set_axisbelow(True)
        return fig, axes

    def title(ax, text):
        ax.set_title(text, loc='left', color=FG, fontsize=14, pad=13)

    def empty(ax):
        ax.text(.5,.5,'No verified measurements\nin this mission yet', ha='center',
                va='center', transform=ax.transAxes, color=MUTED, fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])

    def series(ax, points, ylabel, *, limit=None, divisor=1):
        if not points:
            empty(ax)
            return
        origin = points[0][0] if time_origin is None else time_origin
        ax.plot([(t-origin)/3600 for t,v in points], [v/divisor for t,v in points],
                color=GREEN, marker='.', markersize=4, linestyle=':')
        ax.set_xlabel('Wall hours since first mission observation; dots = reads')
        ax.set_ylabel(ylabel)
        if limit:
            ax.axhline(limit, color=AMBER, linestyle='--', linewidth=1)
        value_axis(ax, [v/divisor for t,v in points], target=limit)

    panel_index = 0
    # Four always-visible charts plus four rotating supporting charts.
    fixed = {0, 1, 6, 11}
    supporting = [i for i in range(16) if i not in fixed]
    page = int(data.get('chart_page', 0)) % 3
    selected = fixed | set(supporting[page*4:page*4+4])

    def panels(fig, filename, caption):
        nonlocal panel_index
        for ax in fig.axes:
            ax.set_xlabel(textwrap.fill(ax.get_xlabel(),75))
            ax.set_ylabel(textwrap.fill(ax.get_ylabel(),45))
        if not focused:
            return [(filename, png(fig), caption)]
        from matplotlib.transforms import Bbox
        output = []
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for ax in fig.axes:
            index = panel_index
            panel_index += 1
            if index not in selected:
                continue
            box = ax.get_tightbbox(renderer).transformed(fig.dpi_scale_trans.inverted())
            box = Bbox.from_extents(box.x0-.15, box.y0-.15, box.x1+.15, box.y1+.15)
            buffer = io.BytesIO()
            fig.savefig(buffer, format='png', facecolor=BG, bbox_inches=box, dpi=140)
            output.append((f'chart_{index:02d}.png', buffer.getvalue(), ax.get_title(loc='left')))
        fig.clear()
        return output

    def png(fig):
        output = io.BytesIO()
        fig.savefig(output, format='png', facecolor=BG)
        fig.clear()
        return output.getvalue()

    fig, axes = figure(3, 'OPERATIONS')
    ax = axes[0]
    title(ax, 'Newly earned Super Wheelspins | mission output')
    points = timed(source.get('progress', []), 'earned')
    series(ax, points, 'Verified new nodes; not saved inventory',
           limit=None if data.get('credit_limited') else data.get('target'))

    ax = axes[1]
    title(ax, 'Buy → mastery → return | last 80 cars')
    cycles = measured_cycles(source)
    recent = cycles[-80:]
    if recent:
        offset=source.get('cycle_offset',0)
        offset=offset if type(offset) is int and offset>=0 else 0
        cycle_run_chart(ax,cycles,target=data.get('cycle_target_seconds',30),start=offset+1)
        for text in ax.texts: text.set_fontsize(9)
        ax.legend(facecolor=BG,labelcolor=FG,fontsize=9,loc='lower right')
    else:
        empty(ax)

    ax = axes[2]
    title(ax, 'Median stage time | last 20 cars')
    stages = {}
    for row in cycles[-20:]:
        for name, seconds in row.get('steps', {}).items():
            if number(seconds) and seconds >= 0:
                stages.setdefault(name, []).append(seconds)
    if stages:
        names = sorted(stages, key=lambda k: median(stages[k]))
        ax.barh([n.replace('_',' ')+f' (n={len(stages[n])})' for n in names], [median(stages[n]) for n in names], color=GREEN)
        value_axis(ax, [median(stages[n]) for n in names], horizontal=True)
        ax.set_xlabel('Seconds per recorded stage (medians do not sum to cycle median)')
    else:
        empty(ax)

    farms,profile = recent_farm_regime(source.get('farms', []))
    ax = axes[3]
    title(ax, f'Retained SP | {profile} · last {len(farms)}')
    valid = [(i+1,r) for i,r in enumerate(farms) if number(r.get('gained_sp')) and r['gained_sp']>=0]
    if valid:
        bars = ax.bar([i for i,r in valid], [r['gained_sp'] for i,r in valid], color=GREEN)
        value_axis(ax, [r['gained_sp'] for i,r in valid])
        for bar, (_, row) in zip(bars,valid):
            if row.get('capped'):
                bar.set_color(AMBER)
                bar.set_edgecolor(BG)
                bar.set_hatch('//')
        ax.set_xlabel('Current regime sample; amber hatch = capped; includes top-ups')
        ax.set_ylabel('SP retained; capped runs understate potential yield')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    else:
        empty(ax)

    ax = axes[4]
    title(ax, f'Challenge duration | {profile} · last {len(farms)}')
    valid = [(i+1,r) for i,r in enumerate(farms) if number(r.get('active_seconds')) and r['active_seconds']>=0]
    if valid:
        bars = ax.bar([i for i,r in valid], [r['active_seconds']/60 for i,r in valid], color=GREEN)
        value_axis(ax, [r['active_seconds']/60 for i,r in valid])
        for bar, (_, row) in zip(bars,valid):
            if row.get('partial_timing') is not False:
                bar.set_color(AMBER)
                bar.set_edgecolor(BG)
                bar.set_hatch('//')
            elif row.get('run_type')=='intentional_top_up':
                bar.set_color(CYAN)
        ax.set_xlabel('Current regime; amber = partial/unknown; cyan = planned top-up')
        ax.set_ylabel('Recorded active minutes')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    else:
        empty(ax)

    ax = axes[5]
    title(ax, 'Challenges per completed batch SP refill')
    refills = [r for r in source.get('refills', [])[-15:] if number(r.get('run_count'))]
    if refills:
        bars = ax.bar(range(1,len(refills)+1), [r['run_count'] for r in refills], color=GREEN)
        value_axis(ax, [r['run_count'] for r in refills])
        for bar,row in zip(bars,refills):
            if number(row.get('active_seconds')):
                ax.annotate(f"{row['active_seconds']/60:.0f}m",
                        (bar.get_x()+bar.get_width()/2, bar.get_height()),
                        xytext=(0,-4), textcoords='offset points',
                        ha='center', va='top', color=BG, fontsize=9)
        ax.set_xlabel('Recent refill | labels = recorded active minutes')
        ax.set_ylabel('Completed challenge runs')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    else:
        empty(ax)
    output = panels(fig, 'operations.png', 'Mission operations — six charts')

    fig, axes = figure(2, 'RESOURCES & ACTIVITY')
    title(axes[0], 'Verified SP balance')
    series(axes[0], timed(source.get('progress', []),'sp','sp_at'), 'Skill points', limit=999)
    title(axes[1], 'Verified credits | observations only')
    series(axes[1], timed(source.get('account', []),'credits','credits_at'), 'Million CR', divisor=1_000_000)
    title(axes[2], 'Verified account level | individual observations')
    levels = timed(source.get('account', []),'level','level_at')
    series(axes[2], levels, 'Level (prestige not inferred)')
    if levels:
        axes[2].lines[0].set_linestyle('none')
        axes[2].text(.02,.96,'Level may reset at prestige; no cross-prestige trend inferred',
                     transform=axes[2].transAxes,color=MUTED,fontsize=9,va='top')
        axes[2].yaxis.set_major_locator(MaxNLocator(integer=True))
    title(axes[3], 'Recorded active time by activity')
    seconds = {k:v for k,v in source.get('seconds', {}).items() if number(v) and v>0}
    if seconds:
        names = list(seconds)
        bars = axes[3].barh(names, [seconds[n]/3600 for n in names], color=GREEN)
        total = sum(seconds.values())
        for bar,name in zip(bars,names):
            inside = seconds[name] >= max(seconds.values())*.15
            axes[3].annotate(f'{seconds[name]/total:.0%}',
                         (bar.get_width(), bar.get_y()+bar.get_height()/2),
                         xytext=(-4 if inside else 4,0), textcoords='offset points',
                         color=BG if inside else FG, ha='right' if inside else 'left',
                         va='center', fontsize=10)
        value_axis(axes[3], [v/3600 for v in seconds.values()], horizontal=True)
        axes[3].set_xlabel('Recorded hours; stopped/offline time excluded')
    else:
        empty(axes[3])
    output.extend(panels(fig, 'resources.png', 'Resources and activity — four charts'))
    op=data.get('analytics',{}).get('operations',{}) if matched else {}
    if op:
        from .operations_metrics import fmt
        fig,axes=figure(3,'THROUGHPUT & RELIABILITY')
        ax=axes[0]; title(ax,'Verified NEW Super Wheelspins / hour')
        ax.axis('off')
        lines=[f"ACTIVE  {fmt(op.get('sw_active_hour'))} SW/h     WALL  {fmt(op.get('sw_wall_hour'))} SW/h",
            f"FARM CAPACITY             {fmt(op.get('farm_capacity'))} cars/h",
            f"CONVERSION CAPACITY       {fmt(op.get('conversion_capacity'))} cars/h",
            f"BOTTLENECK: {op.get('bottleneck','MEASURING')}    IMBALANCE: {fmt(op.get('imbalance_percent'))}%",
            f"Sequential combined capacity: {fmt(op.get('combined_capacity'))} cars/h",
            f"First-pass yield: {fmt(op.get('first_pass_yield'))}%  (n={op.get('first_pass_samples',0)})",
            f"FORZA TAX (OBSERVED RESIDUAL): {fmt(op.get('forza_tax_percent_estimated'),'%')}",
            'Polling/pacing excluded; causal game share unmeasured',
            f"Retained SP / farm hour: {fmt(op.get('retained_sp_hour'))}",
            f"Estimated cap loss: {fmt(op.get('cap_loss_sp_estimated'))} SP / {fmt(op.get('cap_loss_percent_estimated'))}%",
            f"Cap estimates: {op.get('cap_loss_samples',0)} runs; raw SP is not observed"]
        ax.text(0,.96,'\n'.join(lines),transform=ax.transAxes,va='top',color=FG,fontsize=11,linespacing=1.45)
        ax=axes[1]; title(ax,'Stage percentiles | last 20 completed cars')
        percentile_comparison(ax,op.get('stage_percentiles',{}),'Recorded stage seconds')
        for text in ax.texts:text.set_fontsize(8)
        ax.tick_params(axis='y',labelsize=9)
        causes=op.get('failures',{})
        ax=axes[2];title(ax,'Retries per 100 cars | detailed coverage only')
        valid={k:v for k,v in causes.items() if number(v.get('per_100_cars')) and v['per_100_cars']>=0}
        if valid:
            valid=dict(sorted(valid.items(),key=lambda pair:pair[1]['per_100_cars'],reverse=True))
            ax.barh([k.replace('_',' ') for k in valid],[v['per_100_cars'] for v in valid.values()],color=RED)
            ax.invert_yaxis();ax.tick_params(axis='y',labelsize=9)
            value_axis(ax,[v['per_100_cars'] for v in valid.values()],horizontal=True)
            ax.set_xlabel(f"Events / 100 completed cars; denominator n={op.get('first_pass_samples',0)}")
        else: empty(ax)
        ax=axes[3];title(ax,'Recovery cost by cause | recorded seconds')
        costs={k:v for k,v in causes.items() if number(v.get('recovery_seconds')) and v['recovery_seconds']>=0}
        if costs:
            costs=dict(sorted(costs.items(),key=lambda pair:pair[1]['recovery_seconds'],reverse=True))
            ax.barh([k.replace('_',' ') for k in costs],[v['recovery_seconds'] for v in costs.values()],color=RED)
            ax.invert_yaxis();ax.tick_params(axis='y',labelsize=9)
            value_axis(ax,[v['recovery_seconds'] for v in costs.values()],horizontal=True)
            ax.set_xlabel('Failure → checkpoint advancement; includes repeat work')
        else: empty(ax)
        ax=axes[4];title(ax,'Input → usable screen | sampled latency')
        percentile_comparison(ax,{k:v.get('input_to_usable',{}) for k,v in op.get('transition_stages',{}).items()},
                              'Seconds; usable detection is a sampled visual proxy')
        for text in ax.texts:text.set_fontsize(8)
        ax.tick_params(axis='y',labelsize=9)
        ax=axes[5];title(ax,'Time attribution | instrumented completed cars')
        values={('unassigned overhead' if k=='waiting_loading_estimate' else k):v
                for k,v in op.get('attribution',{}).items() if number(v) and v>=0}
        if sum(values.values())>0:
            values=dict(sorted(values.items(),key=lambda pair:pair[1],reverse=True))
            ax.barh([k.replace('_',' ') for k in values],[v/60 for v in values.values()],color=GREEN)
            ax.invert_yaxis()
            value_axis(ax,[v/60 for v in values.values()],horizontal=True)
            ax.set_xlabel('Recorded bucket minutes; causal game share unmeasured')
        else: empty(ax)
        output.extend(panels(fig,'diagnostics.png','Throughput, stage tails, failures and transition latency'))
    return output
