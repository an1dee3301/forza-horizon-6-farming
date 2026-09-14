"""Readable timing comparisons; display limits never change measurements."""
import textwrap
from statistics import median

from .operations_metrics import numeric, percentiles
from .report_charts import value_axis, trend_axis, focused_limits
from .report_theme import BG, FG, GREEN, AMBER, CYAN, MUTED, GRID


def observed_timeline(ax, rows, field, stamp='at', *, divisor=1, addition=0,
                      target=None, ylabel='', origin=None):
    """Point observations do not prove the unobserved intervening balance."""
    from .report_charts import timed
    points = timed(rows, field, stamp)
    if not points:
        ax.text(.5,.5,'No verified observations',transform=ax.transAxes,
                ha='center',color=MUTED)
        ax.set_xticks([]); ax.set_yticks([])
        return
    basis='first shown observation' if origin is None else 'first mission observation'
    origin = points[0][0] if origin is None else origin
    values = [v/divisor+addition for _,v in points]
    ax.plot([(t-origin)/3600 for t,_ in points],values,color=GREEN,
            marker='.',markersize=5,linewidth=1.2,linestyle=':')
    if numeric(target) and target > 0:
        ax.axhline(target,color=AMBER,linestyle='--',linewidth=1.3)
    trend_axis(ax,values,reference=target)
    ax.set_xlabel(f'Wall hours since {basis}; dots = actual reads')
    ax.set_ylabel(ylabel)


def numbered_series(ax, values, ylabel, *, start=1, color=GREEN, log_tails=True, focus=False):
    """Missing samples remain gaps; strong tails remain visible on a named log axis."""
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    clean=[v if numeric(v) and v>=0 else float('nan') for v in values]
    valid=[v for v in clean if numeric(v)]
    if not valid:
        ax.text(.5,.5,'No verified measurements',transform=ax.transAxes,
                ha='center',color=MUTED)
        ax.set_xticks([]);ax.set_yticks([])
        return
    ax.plot(range(start,start+len(values)),clean,color=color,marker='.',linewidth=1.5,markersize=5)
    if focus and len(valid)>=20:
        low,high=focused_limits(valid,minimum_span=.5)
        ax.set_ylim(low,high)
        ax.ticklabel_format(axis='y',style='plain',useOffset=False)
    elif log_tails and min(valid)>0 and max(valid)>10*median(valid):
        ax.set_yscale('log'); ax.yaxis.set_major_formatter(ScalarFormatter())
        ylabel+=' · logarithmic scale'
    else:
        trend_axis(ax,valid,minimum_span=.1)
    ax.set_xlabel('Completed sample in retained mission history')
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6,integer=True))


def cycle_run_chart(ax, cycles, *, target=30, start=1, window=80):
    """User-selected 25–60s view, with every off-scale sample still identified."""
    from matplotlib.ticker import MaxNLocator
    recent=cycles[-window:]
    offset=len(cycles)-len(recent)
    xs=list(range(start+offset,start+len(cycles)))
    values=[r.get('elapsed_seconds') for r in recent]
    visible=[v if numeric(v) and 25<=v<=60 else float('nan') for v in values]
    ax.plot(xs,visible,color=CYAN,marker='.',linewidth=1.3,label='Measured car')
    rolling=[]
    for i in range(offset,len(cycles)):
        samples=[r.get('elapsed_seconds') for r in cycles[max(0,i-19):i+1]]
        valid=[v for v in samples if numeric(v) and v>0]
        rolling.append(median(valid) if len(valid)==20 else float('nan'))
    ax.plot(xs,rolling,color=GREEN,linewidth=2.8,label='Rolling 20 median')
    ax.axhline(target,color=AMBER,linestyle='--',label=f'{target:g}s target')
    marked=[i for i,v in enumerate(values) if numeric(v) and not 25<=v<=60]
    for above,marker,edge in [(True,'^',1.012),(False,'v',-.012)]:
        selected=[i for i in marked if (values[i]>60)==above]
        if selected:
            ax.scatter([xs[i] for i in selected],[edge]*len(selected),
                       transform=ax.get_xaxis_transform(),marker=marker,color=AMBER,s=48,clip_on=False)
    if marked:
        ranked=sorted(marked,key=lambda i:max(25-values[i],values[i]-60),reverse=True)
        note='; '.join(f'#{xs[i]} {values[i]:.1f}s' for i in ranked[:3])
        ax.text(.015,.97,f'Off-scale {len(marked)}: {note}'+(' …' if len(marked)>3 else '')+
                '\nAll retained in statistics',transform=ax.transAxes,va='top',fontsize=12,color=AMBER,
                bbox=dict(facecolor=BG,edgecolor='none',alpha=.93))
    ax.set_ylim(25,60);ax.set_yticks(range(25,61,5))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6,integer=True))
    ax.set_xlabel('Completed sample in retained mission history')
    ax.set_ylabel('Recorded cycle seconds')
    ax.legend(loc='lower right',facecolor=BG,edgecolor=GRID,labelcolor=FG,fontsize=13)


def residual_rows(cycles):
    """No missing residual is zero; only version-2 observed transition sums qualify."""
    result=[]
    for row in cycles:
        timing=row.get('transition_timing') or {}
        total=row.get('elapsed_seconds')
        residual=timing.get('unassigned_within_usable_seconds')
        usable=timing.get('usable_count')
        observed=timing.get('observed_usable_seconds')
        valid=(timing.get('version')==2 and not row.get('telemetry_dropped')
               and numeric(total) and total>0
               and numeric(residual) and 0<=residual<=total
               and numeric(observed) and residual<=observed<=total
               and type(usable) is int and usable>0)
        result.append((residual,total,usable,timing.get('partial_count')) if valid else None)
    return result


def forza_tax_chart(ax, cycles, *, start=1, number=3):
    rows=residual_rows(cycles)
    valid=[r for r in rows if r is not None]
    ax.set_title(f'{number:02d} · Forza tax | observed residual',loc='left',color=FG,fontsize=20,pad=17)
    if not valid:
        ax.text(.5,.5,'No version-2 transition coverage',transform=ax.transAxes,ha='center',color=MUTED)
        ax.set_xticks([]);ax.set_yticks([])
        return
    values=[100*r[0]/r[1] if r else None for r in rows]
    numbered_series(ax,values,'Residual / recorded cycle (%)',start=start,color=CYAN,log_tails=False)
    ax.lines[0].set_label('Observed car residual')
    rolling=[]
    for i in range(len(rows)):
        window=rows[max(0,i-19):i+1]
        rolling.append(100*sum(r[0] for r in window)/sum(r[1] for r in window)
                       if len(window)==20 and all(r is not None for r in window) else float('nan'))
    ax.plot(range(start,start+len(rows)),rolling,color=GREEN,linewidth=2.5,label='20-car duration-weighted share')
    mean=100*sum(r[0] for r in valid)/sum(r[1] for r in valid)
    partial=sum(r[3] for r in valid if type(r[3]) is int and r[3]>=0)
    ax.text(.02,.98,f'Plotted cohort: weighted {mean:.2f}% · {len(valid)}/{len(rows)} cars covered\n'
            f'{sum(r[2] for r in valid):,} usable transitions · {partial:,} incomplete',
            transform=ax.transAxes,va='top',color=MUTED,fontsize=12,
            bbox=dict(facecolor=BG,edgecolor='none',alpha=.9))
    ax.text(0,-.25,'Input→usable less measured polling/pacing. Causal game share unmeasured.',
            transform=ax.transAxes,color=MUTED,fontsize=12)
    ax.legend(loc='lower right',frameon=False,labelcolor=FG,fontsize=11)


def clock_label(seconds):
    if not numeric(seconds) or seconds < 0:
        return 'Unknown'
    seconds = round(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}'


def mini_duration(ax, farms):
    """A dot per run, exact times beside it, including every off-scale value."""
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter

    mini = [r for r in farms if str(r.get('share_code', '')).replace(' ', '') == '169055890']
    rows = list(reversed(list(enumerate(mini, 1))[-20:]))
    def partial(row):
        return row.get('partial_timing') is not False or row.get('run_type') == 'interrupted'

    # A short intentional top-up and a resumed/interrupted measurement are not
    # comparable to a full uninterrupted run. Keep their exact rows visible.
    measured = [r['active_seconds'] for _, r in rows if numeric(r.get('active_seconds'))
                and r['active_seconds'] >= 0 and not partial(r)
                and r.get('run_type') != 'intentional_top_up']
    q = percentiles(measured)
    subtitle = (f"Full runs: P50 {clock_label(q['p50'])} · P90 {clock_label(q['p90'])} · n={q['n']}/{len(rows)}"
                if measured else 'No complete full-run timing yet')
    ax.set_title('02 · Mini V2 time per challenge\n' + subtitle,
                 loc='left', color=FG, fontsize=20, pad=17)
    # Reserve a real column for exact values instead of hiding them in a legend.
    pos = ax.get_position()
    ax.set_position([pos.x0, pos.y0, pos.width * .86, pos.height])
    ax.set_xlim(5, 7)
    ax.set_xticks([5, 5.5, 6, 6.5, 7])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda minutes, _: clock_label(float(minutes) * 60)))
    ax.set_ylim(len(rows) - .35 if rows else .5, -1.5)
    labels, kinds = [], set()
    for y, (ordinal, row) in enumerate(rows):
        run_id = str(row.get('id', '')).rsplit('_', 1)[-1]
        labels.append('#' + (run_id if run_id.isdigit() else str(ordinal)))
        seconds = row.get('active_seconds')
        interrupted = partial(row)
        planned = row.get('run_type') == 'intentional_top_up'
        kind = 'Partial / unknown timing' if interrupted else 'Planned top-up' if planned else 'Complete timing'
        color = AMBER if interrupted else CYAN if planned else GREEN
        marker = 'X' if interrupted else 'D' if planned else 'o'
        valid = numeric(seconds) and seconds >= 0
        if valid:
            kinds.add(kind)
            x = seconds / 60
            if x > 7 or x < 5:
                marker = '>' if x > 7 else '<'
            ax.scatter([min(7, max(5, x))], [y], color=color, marker=marker,
                       s=55, zorder=4, clip_on=False)
        # Flag meanings stay visible even when an out-of-range triangle replaces a dot.
        suffix = (' *' if interrupted else ' †' if planned else '') if valid else ''
        ax.text(1.045, y, clock_label(seconds) + suffix, transform=ax.get_yaxis_transform(),
                color=color if valid else MUTED, fontsize=14, va='center')
    ax.set_yticks(range(len(rows)), labels)
    ax.tick_params(axis='y', labelsize=13)
    ax.text(1.045, -1.05, 'ACTUAL', transform=ax.get_yaxis_transform(), color=MUTED,
            fontsize=12, va='center')
    ax.axvline(410 / 60, color=CYAN, linestyle='--', linewidth=1.4, zorder=2)
    ax.axvline(453 / 60, color=AMBER, linestyle='--', linewidth=1.4, zorder=2)
    ax.grid(False)
    ax.grid(axis='x', color=GRID, linewidth=.8)
    ax.set_xlabel('Active time: setup + drive + exit (m:ss)')
    ax.set_ylabel('Mini run · newest first')
    handles = [Line2D([], [], color=CYAN, linestyle='--', label='6:50 reference'),
               Line2D([], [], color=AMBER, linestyle='--', label='7:33 reference (above view)')]
    for label, color, marker in [('Partial / unknown timing', AMBER, 'X'), ('Planned top-up', CYAN, 'D')]:
        if label in kinds:
            handles.append(Line2D([], [], color=color, marker=marker, linestyle='none',
                                  label=('* ' if marker == 'X' else '† ') + label))
    ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(0, -.15), ncol=2,
              frameon=False, labelcolor=FG, fontsize=12, columnspacing=1)
    ax.text(0, -.31, '◀ / ▶ off-scale · * / † excluded from full-run percentiles',
            transform=ax.transAxes, color=MUTED, fontsize=12, va='top')


def farm_duration(ax, farms, *, share_code=None, number=2):
    """Current contiguous farm regime; historical trials never fill an empty new regime."""
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter
    from .report_charts import recent_farm_regime

    cohort,profile=recent_farm_regime(farms,limit=max(20,len(farms)))
    latest=str(cohort[-1].get('share_code','')).replace(' ','') if cohort else None
    requested=str(share_code).replace(' ','') if share_code else latest
    names={'155439962':'Mega V6','169055890':'Mini V2'}
    profile=names.get(requested,profile)
    if requested and requested!=latest: cohort=[]
    rows=list(reversed(cohort[-20:]))
    def kind(row):
        if row.get('partial_timing') is not False or row.get('run_type')=='interrupted': return 'Partial / unknown'
        return 'Planned top-up' if row.get('run_type')=='intentional_top_up' else 'Full run'
    full=[r['active_seconds'] for r in rows if kind(r)=='Full run' and numeric(r.get('active_seconds')) and r['active_seconds']>0]
    topups=[r['active_seconds'] for r in rows if kind(r)=='Planned top-up' and numeric(r.get('active_seconds')) and r['active_seconds']>0]
    q=percentiles(full)
    ax.set_title(f'{number:02d} · {profile} | challenge active time',loc='left',color=FG,fontsize=20,pad=17)
    if not rows:
        ax.text(.5,.5,'No completed runs in the current profile regime',transform=ax.transAxes,
                ha='center',va='center',color=MUTED,fontsize=16,wrap=True)
        ax.set_xticks([]);ax.set_yticks([])
        return
    pos=ax.get_position();ax.set_position([pos.x0,pos.y0,pos.width*.84,pos.height])
    valid=[r['active_seconds']/60 for r in rows if numeric(r.get('active_seconds')) and r['active_seconds']>0]
    # Full runs and planned top-ups are both intentional production runs, so
    # the shared time axis must show their actual positions. Interrupted or
    # otherwise partial timings remain edge-marked when they fall outside the
    # production range, while their exact values stay in the ACTUAL column.
    production=[v/60 for v in full+topups]
    limits=focused_limits(production or valid,minimum_span=1) or (0,20)
    ax.set_xlim(*limits);ax.xaxis.set_major_formatter(FuncFormatter(lambda m,_:clock_label(float(m)*60)))
    ax.set_ylim(len(rows)-.35,-1.4)
    colors={'Full run':GREEN,'Planned top-up':CYAN,'Partial / unknown':AMBER}
    markers={'Full run':'o','Planned top-up':'D','Partial / unknown':'X'}
    labels=[]
    for y,row in enumerate(rows):
        identifier=str(row.get('id','')).rsplit('_',1)[-1]
        labels.append('#'+(identifier if identifier.isdigit() else str(len(cohort)-y)))
        seconds=row.get('active_seconds');category=kind(row);color=colors[category]
        marker=markers[category];valid=numeric(seconds) and seconds>0
        if valid:
            x=seconds/60
            marker='<' if x<limits[0] else '>' if x>limits[1] else marker
            ax.scatter([min(limits[1],max(limits[0],x))],[y],color=color,marker=marker,s=58,clip_on=False,zorder=4)
        suffix=(' †' if category=='Planned top-up' else ' *' if category=='Partial / unknown' else '') if valid else ''
        ax.text(1.035,y,clock_label(seconds)+suffix,transform=ax.get_yaxis_transform(),
                va='center',color=color if valid else MUTED,fontsize=14)
    ax.set_yticks(range(len(rows)),labels);ax.tick_params(axis='y',labelsize=13)
    ax.text(1.035,-.95,'ACTUAL',transform=ax.get_yaxis_transform(),color=MUTED,fontsize=12)
    ax.grid(False);ax.grid(axis='x',color=GRID,linewidth=.8)
    ax.set_xlabel('Active time: setup + drive + exit (m:ss)');ax.set_ylabel('Current regime · newest first')
    ax.legend(handles=[Line2D([],[],color=colors[k],marker=markers[k],linestyle='none',label=k) for k in colors],
              loc='upper left',bbox_to_anchor=(0,-.15),frameon=False,labelcolor=FG,fontsize=12,ncol=2)
    complete_note=(f"Full runs: P50 {clock_label(q['p50'])} · P90 {clock_label(q['p90'])} · n={q['n']}/{len(rows)}"
                   if full else f'Full runs: no complete timing / {len(rows)} observations')
    topup_note=f'Top-up P50 {clock_label(median(topups))} · n={len(topups)}' if topups else 'No complete top-up timing'
    ax.text(0,-.34,complete_note+'\n'+topup_note+' · shared axis; partial/unknown may be ◀/▶ off-scale',
            transform=ax.transAxes,color=MUTED,fontsize=12,va='top')


def refill_output_chart(ax, refills, *, number=12, window=20):
    """One row per refill: exact retained output, run count and active time."""
    from .report_charts import focused_limits

    indexed=list(enumerate(refills,1))[-window:]
    rows=list(reversed(indexed))
    ax.set_title(f'{number:02d} · Refill output, duration and runs | last {window}',
                 loc='left',color=FG,fontsize=20,pad=17)
    if not rows:
        ax.text(.5,.5,'No completed refills yet',transform=ax.transAxes,
                ha='center',va='center',color=MUTED,fontsize=16)
        ax.set_xticks([]);ax.set_yticks([])
        return

    # Keep the plot relational while reserving a real column for exact values.
    pos=ax.get_position();ax.set_position([pos.x0,pos.y0,pos.width*.76,pos.height])
    durations=[];complete_times=[];complete_gains=[]
    labels=[]
    for _,row in indexed:
        seconds=row.get('active_seconds')
        if numeric(seconds) and seconds>0: durations.append(seconds/60)
        nested=row.get('farms') or []
        covered=bool(nested) and all(r.get('partial_timing') is False for r in nested)
        before,after=row.get('before_sp'),row.get('after_sp')
        gain=after-before if type(before) is int and type(after) is int and after>=before else None
        if covered and numeric(seconds) and seconds>0:
            complete_times.append(seconds)
            if numeric(gain): complete_gains.append(gain)
    limits=focused_limits(durations,minimum_span=2) or (0,60)
    ax.set_xlim(*limits);ax.set_ylim(len(rows)-.35,-1.4)
    for y,(ordinal,row) in enumerate(rows):
        labels.append(f'#{ordinal}')
        seconds=row.get('active_seconds');minutes=seconds/60 if numeric(seconds) and seconds>0 else None
        nested=row.get('farms') or []
        covered=bool(nested) and all(r.get('partial_timing') is False for r in nested)
        before,after=row.get('before_sp'),row.get('after_sp')
        gain=after-before if type(before) is int and type(after) is int and after>=before else None
        runs=row.get('run_count') if type(row.get('run_count')) is int else None
        color=GREEN if covered else AMBER
        if numeric(minutes):
            marker='o' if covered else 'X'
            clipped=min(limits[1],max(limits[0],minutes))
            if minutes<limits[0]: marker='<'
            elif minutes>limits[1]: marker='>'
            ax.scatter([clipped],[y],marker=marker,color=color,s=62,zorder=4,clip_on=False)
        else:
            color=MUTED
        detail=(f"+{gain:,} SP" if type(gain) is int else '+— SP')+' · '+(
                f'{runs} run'+('s' if runs!=1 else '') if runs is not None else '— runs')+' · '+clock_label(seconds)
        ax.text(1.045,y,detail,transform=ax.get_yaxis_transform(),va='center',
                color=color,fontsize=12.5)
    ax.set_yticks(range(len(rows)),labels);ax.tick_params(axis='y',labelsize=12)
    ax.text(1.045,-.95,'RETAINED · RUNS · ACTIVE',transform=ax.get_yaxis_transform(),
            color=MUTED,fontsize=11)
    ax.grid(False);ax.grid(axis='x',color=GRID,linewidth=.8)
    ax.set_xlabel('Recorded refill active minutes · focused scale')
    ax.set_ylabel('Completed refill · newest first')
    time_q=percentiles(complete_times);gain_q=percentiles(complete_gains)
    note=(f"Complete timing: P50 {clock_label(time_q['p50'])} · P90 {clock_label(time_q['p90'])} · "
          f"median +{gain_q['p50']:.0f} SP · n={time_q['n']}/{len(rows)}"
          if complete_times and complete_gains else f'Complete timing unavailable · 0/{len(rows)}')
    ax.text(0,-.27,note+'\nX = refill containing partial/unknown run timing; exact results remain shown',
            transform=ax.transAxes,color=MUTED,fontsize=12,va='top')


def farm_rate_chart(ax, farms, *, share_code=None, number=14, window=20):
    """Per-run rate plus duration-weighted rolling and cohort rates."""
    from .report_charts import recent_farm_regime

    cohort,profile=recent_farm_regime(farms,limit=max(window,len(farms)))
    latest=str(cohort[-1].get('share_code','')).replace(' ','') if cohort else None
    requested=str(share_code).replace(' ','') if share_code else latest
    names={'155439962':'Mega V6','169055890':'Mini V2'}
    profile=names.get(requested,profile)
    if requested and requested!=latest: cohort=[]
    rows=cohort[-window:]
    ax.set_title(f'{number:02d} · {profile} retained-SP rate | last {window}',
                 loc='left',color=FG,fontsize=20,pad=17)
    if not rows:
        ax.text(.5,.5,'No completed runs in the current profile regime',transform=ax.transAxes,
                ha='center',va='center',color=MUTED,fontsize=16)
        ax.set_xticks([]);ax.set_yticks([])
        return

    def eligible(row):
        before,after=row.get('before_sp'),row.get('after_sp')
        return (row.get('partial_timing') is False and type(before) is int and type(after) is int
                and after>=before and numeric(row.get('gained_sp')) and row['gained_sp']>=0
                and numeric(row.get('active_seconds')) and row['active_seconds']>0)
    def run_number(row,fallback):
        identifier=str(row.get('id','')).rsplit('_',1)[-1]
        return int(identifier) if identifier.isdigit() else fallback
    base=max(1,len(cohort)-len(rows)+1)
    xs=[run_number(row,base+i) for i,row in enumerate(rows)]
    valid=[(x,row,row['gained_sp']*3600/row['active_seconds'])
           for x,row in zip(xs,rows) if eligible(row)]
    if not valid:
        ax.text(.5,.5,'No complete run timing with an actual SP balance',transform=ax.transAxes,
                ha='center',va='center',color=MUTED,fontsize=16)
        ax.set_xticks([]);ax.set_yticks([])
        return
    full=[(x,r,v) for x,r,v in valid if r.get('run_type')!='intentional_top_up']
    topups=[(x,r,v) for x,r,v in valid if r.get('run_type')=='intentional_top_up']
    for subset,color,marker,label in [(full,GREEN,'o','Full run'),(topups,CYAN,'D','Planned top-up')]:
        if subset:
            ax.scatter([x for x,_,_ in subset],[v for _,_,v in subset],color=color,
                       marker=marker,s=48,label=label,zorder=4)
    rolling=[]
    for i in range(len(valid)):
        block=valid[max(0,i-4):i+1]
        rolling.append(sum(r['gained_sp'] for _,r,_ in block)*3600/
                       sum(r['active_seconds'] for _,r,_ in block) if len(block)==5 else float('nan'))
    ax.plot([x for x,_,_ in valid],rolling,color=FG,linewidth=2.0,label='Rolling 5 · duration weighted')
    cohort_valid=[r for r in cohort if eligible(r)]
    cohort_rate=sum(r['gained_sp'] for r in cohort_valid)*3600/sum(r['active_seconds'] for r in cohort_valid)
    ax.axhline(cohort_rate,color=AMBER,linestyle='--',linewidth=1.5,label='Current-regime rate')
    rates=[v for _,_,v in valid]+[v for v in rolling if numeric(v)]+[cohort_rate]
    trend_axis(ax,rates,reference=cohort_rate,minimum_span=100)
    excluded=[x for x,row in zip(xs,rows) if not eligible(row)]
    if excluded:
        ax.scatter(excluded,[.015]*len(excluded),transform=ax.get_xaxis_transform(),
                   marker='X',color=AMBER,s=50,clip_on=False,label='Excluded timing')
    ax.set_xlabel('Farm run in retained mission history')
    ax.set_ylabel('Retained SP / recorded active hour')
    ax.grid(False);ax.grid(axis='y',color=GRID,linewidth=.8)
    ax.legend(loc='lower right',facecolor=BG,edgecolor=GRID,labelcolor=FG,fontsize=10)
    recent5=next((v for v in reversed(rolling) if numeric(v)),None)
    summary=f'Cohort {cohort_rate:,.0f} SP/h = {cohort_rate/21:,.1f} cars/h'
    if numeric(recent5): summary+=f' · rolling 5 {recent5:,.0f} SP/h'
    ax.text(0,-.27,summary,transform=ax.transAxes,color=MUTED,fontsize=12,va='top')
    ax.text(0,-.37,f'n={len(valid)}/{len(rows)} shown runs · rates use retained SP and complete active timing; X excluded',
            transform=ax.transAxes,color=MUTED,fontsize=12,va='top')


def percentile_comparison(ax, stats, xlabel):
    """One interval per stage exposes tail spread without three dense bar rows."""
    from matplotlib.lines import Line2D

    rows = [(name, q) for name, q in stats.items() if type(q.get('n')) is int and q['n']>0
            and all(numeric(q.get(k)) for k in ('p50', 'p90', 'p99'))
            and 0<=q['p50']<=q['p90']<=q['p99']]
    rows.sort(key=lambda item: item[1]['p50'], reverse=True)
    if not rows:
        ax.text(.5, .5, 'No verified measurements yet', transform=ax.transAxes,
                color=MUTED, fontsize=18, ha='center')
        ax.set_xticks([]); ax.set_yticks([])
        return
    vals = [q[k] for _, q in rows for k in ('p50', 'p90', 'p99')]
    value_axis(ax, vals, horizontal=True)
    medians=[q['p50'] for _,q in rows if numeric(q['p50']) and q['p50']>0]
    if medians and max(vals)>10*median(medians):
        # Preserve extreme delays without compressing every ordinary stage
        # into the first few pixels. Explicit ticks keep seconds readable.
        ax.set_xscale('symlog',linthresh=1)
        ticks=[v for v in (0,1,3,10,30,100,300,1000,3000,10000) if v<=max(vals)*1.08]
        ax.set_xticks(ticks,[str(v) for v in ticks])
        xlabel += ' · log spacing above 1s'
    for y, (_, q) in enumerate(rows):
        ax.plot([q['p50'], q['p99']], [y, y], color=MUTED, linewidth=2, zorder=2)
        for key, color, marker in [('p50', GREEN, 'o'), ('p90', CYAN, 'D'), ('p99', AMBER, '|')]:
            ax.scatter([q[key]], [y], color=color, marker=marker,
                       s=95 if key == 'p99' else 65, linewidths=2, zorder=3)
        ax.annotate(f"{q['p50']:.1f}", (q['p50'], y), xytext=(0, 10),
                    textcoords='offset points', color=GREEN, fontsize=13, ha='center')
    def sample_label(q):
        total=q.get('total')
        return f"n={q['n']}/{total}" if type(total) is int and total>=q['n'] else f"n={q['n']}"
    ax.set_yticks(range(len(rows)), [textwrap.fill(name.replace('_', ' '), 21)
                                    + ('\n' if '/' in sample_label(q) else '  ')
                                    + f"({sample_label(q)})" for name, q in rows])
    ax.set_ylim(len(rows) - .45, -.75)
    ax.set_xlabel(xlabel)
    ax.grid(False); ax.grid(axis='x', color=GRID, linewidth=.8)
    handles = [Line2D([], [], color=color, marker=marker, linestyle='none', label=key)
               for key, color, marker in [('P50', GREEN, 'o'), ('P90', CYAN, 'D'), ('P99', AMBER, '|')]]
    ax.legend(handles=handles, loc='lower right', frameon=False, labelcolor=FG,
              fontsize=14, ncol=3)
    if any(q['n'] < 100 for _, q in rows):
        ax.text(0, -.23, 'P99 = observed maximum when n<100; P90 also when n<10.\nSparse tails are not stable estimates.', transform=ax.transAxes,
                fontsize=12, color=MUTED,va='top')
