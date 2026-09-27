"""Export allowlisted, anonymous operation analytics; never modify source records.

python tools/analyze_operation.py --runs /private/runs
python tools/analyze_operation.py --render-only  # regenerate charts from public CSV

Naive source timestamps are interpreted as Japan local time. UTC inventory
timestamps retain their offsets. Public timestamps are elapsed seconds only.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/latest-operation'
DOC = ROOT / 'docs/latest-operation'
JST = timezone(timedelta(hours=9))

def stamp(value):
    d = datetime.fromisoformat(value)
    return d.replace(tzinfo=JST) if d.tzinfo is None else d

def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def write_csv(name, rows, fields):
    with (DATA / (name + '.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def export(runs):
    goal = json.loads((runs / 'goal.json').read_text(encoding='utf-8'))
    gid = goal['id']; start = stamp(goal['started_at'])
    audit = {}; source = {}
    def read(name):
        rows = []; malformed = 0; duplicate = 0; seen = set()
        for line in (runs / (name + '.jsonl')).read_text(encoding='utf-8').splitlines():
            try: row = json.loads(line)
            except (ValueError, TypeError): malformed += 1; continue
            key = json.dumps(row, sort_keys=True)
            if key in seen: duplicate += 1; continue
            seen.add(key); rows.append(row)
        audit[name] = {'input_lines': len(seen) + duplicate + malformed, 'exact_duplicates_removed': duplicate, 'malformed_lines_excluded': malformed}
        source[name] = rows
        return rows
    def sec(v): return round((stamp(v)-start).total_seconds(), 3)
    farms = []; seen = set(); conflicts = 0
    for r in read('analytics_farms'):
        if not r.get('id', '').startswith(gid + '_'): continue
        if r['id'] in seen: conflicts += 1; continue
        seen.add(r['id'])
        wall = (stamp(r['ended_at'])-stamp(r['started_at'])).total_seconds()
        gain = r.get('gained_sp'); valid = finite(gain) and wall > 0
        farms.append(dict(run=len(farms)+1, start_seconds=sec(r['started_at']), wall_seconds=wall, active_seconds=r.get('active_seconds'), drive_seconds=r.get('drive_seconds'), gained_sp=gain, sp_per_wall_hour=round(gain*3600/wall,3) if valid else '', partial_timing=bool(r.get('partial_timing')), capped=bool(r.get('capped')), exit_reason=r.get('exit_reason') if r.get('exit_reason') in {'stationary_recovery_exit', 'natural_completion'} else 'unknown'))
    audit['analytics_farms']['duplicate_run_keys_excluded'] = conflicts
    write_csv('farms', farms, list(farms[0]))
    cycles = []; seen = set(); stages = defaultdict(list); conflict = 0
    for r in read('analytics_cycles'):
        if r.get('goal_id') != gid: continue
        key = (r.get('batch_id'),r.get('cycle'))
        if key in seen: conflict += 1; continue
        seen.add(key)
        elapsed = r.get('elapsed_seconds')
        if not finite(elapsed) or elapsed < 0: continue
        cycles.append(dict(cycle=len(cycles)+1, end_seconds=sec(r['ended_at']), active_cycle_seconds=round(elapsed,3), failed_attempts=r.get('failed_attempts',0)))
        for k,v in r.get('steps',{}).items():
            if k in {'collection','buy','bought','choose','open_mastery','mastery','return'} and finite(v) and v >= 0: stages[k].append(v)
    audit['analytics_cycles']['duplicate_cycle_keys_excluded'] = conflict
    write_csv('cycles', cycles, list(cycles[0]))
    stage_rows = [dict(stage=k, samples=len(v), median_seconds=round(statistics.median(v),3), total_seconds=round(sum(v),3)) for k,v in stages.items()]
    write_csv('stages', stage_rows, list(stage_rows[0]))
    clean = []; seen=set()
    for r in read('analytics_garage_cleanup'):
        if r.get('goal_id') != gid: continue
        key=r.get('operation_id') or (r.get('at'),r.get('removed_total'))
        if key in seen: continue
        seen.add(key)
        clean.append(dict(removal=len(clean)+1, elapsed_seconds=sec(r['at']), count=r.get('count',1)))
    write_csv('cleanup', clean, ['removal','elapsed_seconds','count'])
    # Only the final native-to-native interval is a headline metric. Historical
    # accounting epochs are not joined or silently rebased into a synthetic curve.
    proofs = sorted([r for r in read('inventory_proofs') if r.get('goal_id') == gid and r.get('proof') == 'two_fresh_my_horizon_frames'],key=lambda r:stamp(r['observed_at']))
    endpoints = proofs[-2:]
    native = [dict(observation=i+1, elapsed_seconds=sec(r['observed_at']), super_wheelspins=r['super_wheelspins'], regular_wheelspins=r['wheelspins']) for i,r in enumerate(endpoints)]
    write_csv('native_interval', native, list(native[0]))
    interval = native[-1]['elapsed_seconds']-native[0]['elapsed_seconds']
    gain = native[-1]['super_wheelspins']-native[0]['super_wheelspins']
    events = [r for r in read('analytics_events') if r.get('goal_id') == gid]
    cleanup_end = max(stamp(r['at']) for r in events if r.get('garage_cleanup')=='completed' and r.get('error') is None)
    stop = stamp(goal['credit_stop_proof']['checked_at'])
    final_removals = sum(r['count'] for r in clean if r['elapsed_seconds'] >= (stop-start).total_seconds())
    # Failure records lack a goal ID: report only time-scoped records, not unique
    # incidents or disjoint downtime (durations can overlap cleanup and retries).
    failures=[]
    for r in read('analytics_failures'):
        if not r.get('started_at'): continue
        t=stamp(r['started_at'])
        if start <= t <= cleanup_end:
            failures.append(dict(record=len(failures)+1, start_seconds=sec(r['started_at']), recovery_wall_seconds=r.get('recovery_wall_seconds',''), stage=r.get('stage','unknown') if r.get('stage','') in {'garage_cleanup','farm','farm_drive','farm_prepare','farm_search','farm_leave','farm_read_sp','inspect_sp','choose','buy','mastery','return','open_mastery','collection','game_restart'} else 'other'))
    write_csv('recovery_records',failures,['record','start_seconds','recovery_wall_seconds','stage'])
    vals=[r['active_cycle_seconds'] for r in cycles]; q=statistics.quantiles(vals,n=4)
    fence=q[2]+1.5*(q[2]-q[0])
    audit['cycle_outliers']={'method':'upper Tukey fence, retained', 'threshold_seconds':round(fence,3),'count':sum(v>fence for v in vals)}
    audit['coverage']={'farm_records':len(farms),'goal_farm_counter':goal['farm_runs'],'cycle_records':len(cycles),'goal_completed_counter':goal['completed'],'missing_cycle_records_vs_counter':goal['completed']-len(cycles),'partial_timing_farms':sum(r['partial_timing'] for r in farms),'capped_farms':sum(r['capped'] for r in farms),'failure_records_time_scoped':len(failures),'native_proofs_available':len(proofs),'native_proofs_used_for_final_interval':len(endpoints)}
    summary={'schema_version':1,'goal_state':goal['phase'],'end_reason':goal['end_reason'],'final_native_credits':goal['credit_stop_proof']['observed_credits'],'final_native_super_wheelspins':native[-1]['super_wheelspins'],'final_native_regular_wheelspins':native[-1]['regular_wheelspins'],'final_native_sp':None,'last_observed_sp':goal['last_sp'],'goal_completed_cars':goal['completed'],'native_interval_gain':gain,'native_interval_wall_seconds':interval,'native_interval_sw_per_hour':round(gain*3600/interval,3),'two_adjacent_100_gain_windows_pass':False,'final_cleanup_wall_seconds':round((cleanup_end-stop).total_seconds(),3),'final_cleanup_journal_removals':final_removals,'final_cleanup_status':'verified_empty','cycle_median_active_seconds':round(statistics.median(vals),3),'farm_total_gain':sum(r['gained_sp'] for r in farms if finite(r['gained_sp'])),'farm_total_wall_seconds':sum(r['wall_seconds'] for r in farms),'farm_weighted_sp_per_wall_hour':round(sum(r['gained_sp'] for r in farms if finite(r['gained_sp']))*3600/sum(r['wall_seconds'] for r in farms),3)}
    (DATA/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (DATA/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')

def bars(name,title,subtitle,labels,values,unit,color='#6475ee'):
    width=1000; height=180+len(labels)*48; maximum=max(max(values),1)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',f'<rect width="1000" height="{height}" rx="18" fill="#101722"/>','<g font-family="Arial,sans-serif" fill="#edf2fa">',f'<text x="36" y="48" font-size="26" font-weight="700">{escape(title)}</text>',f'<text x="36" y="78" fill="#a6b3c5" font-size="14">{escape(subtitle)}</text>']
    for i,(label,value) in enumerate(zip(labels,values)):
        y=120+i*48; w=value/maximum*560
        parts.extend([f'<text x="36" y="{y+20}" font-size="15">{escape(label)}</text>',f'<rect x="265" y="{y}" width="{w:.2f}" height="28" rx="5" fill="{color}"/>',f'<text x="{280+w:.2f}" y="{y+20}" font-size="14">{value:,.1f} {unit}</text>'])
    parts.append('</g></svg>'); (DOC/(name+'.svg')).write_text('\n'.join(parts),encoding='utf-8')

def render():
    s=json.loads((DATA/'summary.json').read_text()); a=json.loads((DATA/'audit.json').read_text())
    with (DATA/'stages.csv').open() as f: stages=list(csv.DictReader(f))
    stages.sort(key=lambda r:float(r['median_seconds']),reverse=True)
    bars('conversion-stages','Where conversion time goes','Median recorded stage duration; these are active timings, not independent causal game costs.',[r['stage'].replace('_',' ').title() for r in stages],[float(r['median_seconds']) for r in stages],'s')
    bars('saved-wheelspin-rate','Saved Super Wheelspins: measured result','Final native-to-native interval includes conversion, recovery, idle time and final cleanup.',['Observed interval','Requested target'],[s['native_interval_sw_per_hour'],33],'SW/h','#40bda2')
    with (DATA/'farms.csv').open() as f: farms=list(csv.DictReader(f))
    # Full sequence retained in CSV; contiguous groups make the README readable.
    groups=[farms[i:i+10] for i in range(0,len(farms),10)]
    bars('farm-throughput','Farm throughput across the operation','SP gained / recorded farm wall time; conversion and garage cleanup excluded.',[f"Runs {g[0]['run']}-{g[-1]['run']}" for g in groups],[sum(float(r['gained_sp']) for r in g)*3600/sum(float(r['wall_seconds']) for r in g) for g in groups],'SP/h')
    text=f'''# Latest operation: normalized evidence

The operation stopped purchasing at **{s['final_native_credits']:,} CR**. Final native inventory: **{s['final_native_super_wheelspins']:,} Super Wheelspins** and **{s['final_native_regular_wheelspins']:,} regular Wheelspins**. Final SP is **unavailable**: the last observation predates the final conversions. No estimated balance is presented as native evidence.

## Outcome and rate

The final two native observations added **{s['native_interval_gain']} SW** over **{s['native_interval_wall_seconds']/3600:.3f} hours**, or **{s['native_interval_sw_per_hour']:.2f} saved SW/hour**. The denominator includes all elapsed time and final cleanup. This is one interval, not two adjacent qualifying windows; **33 saved SW/hour remains unproved**. The endpoint is local native inventory, not proof of a cloud upload.

Final cleanup reached verified empty. The journal contains **{s['final_cleanup_journal_removals']} removals after the stopping-floor check**, over **{s['final_cleanup_wall_seconds']/60:.2f} elapsed minutes**, including recovery. Journal records and lifetime running totals are different quantities; lifetime removal counters are deliberately not exported as this cleanup's count.

## Coverage and data quality

- {a['coverage']['farm_records']} distinct farm records versus a goal counter of {a['coverage']['goal_farm_counter']}; this gap is retained, not filled with invented runs.
- {a['coverage']['cycle_records']} distinct cycle records versus {s['goal_completed_cars']} completed cars; {a['coverage']['missing_cycle_records_vs_counter']} missing cycle records. Missing telemetry does not mean missing rewards.
- {a['coverage']['partial_timing_farms']} farm records flag partial timing; {a['coverage']['capped_farms']} flag capped yield. These remain in the dataset with flags.
- {a['cycle_outliers']['count']} cycle observations exceed the upper Tukey fence ({a['cycle_outliers']['threshold_seconds']:.2f} s); outliers are retained, not trimmed to improve speed.
- {a['coverage']['failure_records_time_scoped']} failure records fall within operation time. They have no goal key, so they are time-scoped evidence, not a count of independent incidents. Their durations can overlap; do not add them to wall time.
- Stage sample counts vary; absent stage timings remain missing, not zero-filled. File input-quality counts cover each entire source file, while coverage and exported records are scoped to this operation.
- Exact duplicate JSON rows are removed before entity-key deduplication. First entity record wins; exclusions and malformed lines are counted in `audit.json`. Originals are untouched.

## Timing semantics

Farm wall time is `ended_at - started_at`; recorded active and drive durations are separate columns. Weighted farm throughput is **{s['farm_weighted_sp_per_wall_hour']:.1f} SP/hour**, excluding conversion/cleanup and subject to the timing flags. Median recorded conversion duration is **{s['cycle_median_active_seconds']:.2f} active seconds/car**. Stage medians do not sum to a median cycle and cannot isolate causal loading cost. These are observational diagnostics, not randomized experiment results or universal hardware benchmarks.

Naive source timestamps are interpreted in Japan time (UTC+09:00); offset-aware native timestamps preserve their offset. Public times are seconds since operation start. CSVs contain only explicit allowlisted measures, anonymous sequential row IDs and fixed stage labels; no account IDs, process IDs, paths, screenshots, purchase receipts or message text are copied.

## Reproduce

Run `python tools/analyze_operation.py --render-only` from the repository to reproduce SVG charts from the committed CSVs. To reproduce extraction, provide the private run directory with `--runs /path/to/runs`; the script only reads it. Python standard library only. The source captures are intentionally not distributed.

### Data dictionary

| File | Grain | Interpretation |
|---|---|---|
| farms.csv | One recorded farm | SP gain, wall/active/drive seconds, partial/cap flags |
| cycles.csv | One recorded paid-car cycle | Recorded active duration, end time, failed attempts |
| stages.csv | Stage aggregate | Sample count, median and sum of recorded seconds |
| cleanup.csv | One journal removal | Relative time and removal count, no vehicle/account IDs |
| recovery_records.csv | Time-scoped failure record | Recorded recovery wall time; may overlap |
| native_interval.csv | Final two verified observations | Local native SW/regular balances |
| summary.json | Operation outcome | Native balances, coverage-aware rates, cleanup result |
| audit.json | Input quality | Duplicates, malformed lines, missing coverage and outliers |

![Conversion stages](conversion-stages.svg)
![Saved SW rate](saved-wheelspin-rate.svg)
![Farm throughput](farm-throughput.svg)
'''
    (DOC/'REPORT.md').write_text(text,encoding='utf-8')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--runs',type=Path); p.add_argument('--render-only',action='store_true'); args=p.parse_args()
    DATA.mkdir(parents=True,exist_ok=True); DOC.mkdir(parents=True,exist_ok=True)
    if args.runs: export(args.runs)
    elif not args.render_only: p.error('use --runs or --render-only')
    render()
