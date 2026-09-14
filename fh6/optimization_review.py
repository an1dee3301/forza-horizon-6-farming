"""Read-only, bounded evidence for performance reviews; never change game inputs.

``snapshot()`` reads the existing mission measurements. It does not export files,
send reports, or tune settings. A revision comparison needs real cycle-start
timestamps: elapsed_seconds is active time and cannot establish a wall-clock
start across a pause. Uncertain boundaries stay out of revision comparisons.
"""
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .operations_metrics import percentiles


STAGES = ('buy', 'choose', 'open_mastery', 'mastery', 'return')
WINDOW = 20
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_STEP_BYTES = 8 * 1024 * 1024
MINI = '169055890'
READ_ATTEMPTS = 3
READ_RETRY_SECONDS = .01


def _number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def _stamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return result.astimezone().timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _key(row):
    batch, cycle = row.get('batch_id'), row.get('cycle')
    return (batch, cycle) if isinstance(batch, str) and batch and type(cycle) is int and cycle > 0 else None


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _cycle_starts(step_rows, goal_id):
    starts = {}
    for row in step_rows:
        if not isinstance(row, dict) or row.get('goal_id') != goal_id or row.get('phase') != 'collection':
            continue
        key, start = _key(row), _stamp(row.get('started_at'))
        if key and start is not None:
            starts[key] = min(starts.get(key, start), start)
    return starts


def _health(rows, source):
    """Use only instrumented, completed cars for retry denominators and FPY."""
    telemetry_complete = not source.get('telemetry_dropped')
    covered = [r for r in rows if r.get('recovery_tracking_version') == 2] if telemetry_complete else []
    keys = {_key(r) for r in covered}
    failures = [r for r in _rows(source.get('failures')) if _key(r) in keys]
    causes = defaultdict(lambda: {'count': 0, 'recovery_seconds': 0, 'cost_samples': 0})
    by_cycle = Counter()
    for row in failures:
        by_cycle[_key(row)] += 1
        entry = causes[str(row.get('cause') or 'unclassified')]
        entry['count'] += 1
        cost = row.get('recovery_seconds')
        if _number(cost):
            entry['recovery_seconds'] += cost
            entry['cost_samples'] += 1
    event_count = sum(max(r.get('recovery_events', 0) if _number(r.get('recovery_events', 0)) else 0,
                          by_cycle[_key(r)]) for r in covered)
    clean = sum(not r.get('recovery_events', 0) and not r.get('failed_attempts', 0)
                and not by_cycle[_key(r)] for r in covered)
    for entry in causes.values():
        entry['per_100_cars'] = 100 * entry['count'] / len(covered)
        if not entry['cost_samples']:
            entry['recovery_seconds'] = None
    return {'first_pass_yield_percent': 100 * clean / len(covered) if covered else None,
            'covered_cars': len(covered), 'total_cars': len(rows),
            'coverage_percent': 100 * len(covered) / len(rows) if rows else None,
            'recovery_events': event_count if covered else None,
            'failed_stage_attempts': sum(r.get('failed_attempts', 0) for r in covered
                                         if _number(r.get('failed_attempts', 0))) if covered else None,
            'classified_failure_rows': len(failures), 'causes': dict(causes),
            'unclassified_recovery_events': max(0, event_count - len(failures)) if covered else None,
            'unavailable_reason': ('telemetry_dropped_cannot_locate_missing_events' if not telemetry_complete else
                                   'no_instrumented_completed_cars' if not covered else None)}


def _cohort(rows, source):
    stages = {name: percentiles(row['steps'][name] for row in rows) for name in STAGES}
    timing = percentiles(row['elapsed_seconds'] for row in rows)
    total = sum(row['elapsed_seconds'] for row in rows)
    consumers = sorted(({'stage': name, **stats,
                         'recorded_seconds': sum(row['steps'][name] for row in rows)}
                        for name, stats in stages.items()),
                       key=lambda value: value['recorded_seconds'], reverse=True)
    return {'cars': len(rows), 'complete_window': len(rows) == WINDOW,
            'cycle_seconds': timing, 'stage_seconds': stages,
            'largest_stage_consumers': consumers,
            'effective_conversion_cars_hour': 3600 * len(rows) / total if total > 0 else None,
            'sample_keys': [list(_key(row)) for row in rows],
            'first_ended_at': rows[0]['ended_at'] if rows else None,
            'last_ended_at': rows[-1]['ended_at'] if rows else None,
            'health': _health(rows, source)}


def _rates(goal, source, now):
    earned = goal.get('rewards')
    categories = source.get('seconds')
    active = (sum(categories.values()) if isinstance(categories, dict) and categories
              and all(_number(n) for n in categories.values()) else None)
    if active is None and _number(goal.get('active_seconds')):
        active = goal['active_seconds']
    start, end = _stamp(goal.get('started_at')), _stamp(now)
    wall = end - start if start is not None and end is not None and end > start else None
    reward_valid = type(earned) is int and earned >= 0
    rate = lambda duration: earned * 3600 / duration if reward_valid and _number(duration) and duration > 0 else None
    return {'verified_new_sw': earned if reward_valid else None,
            'sw_active_hour': rate(active), 'sw_wall_hour': rate(wall),
            'active_seconds': active, 'wall_seconds': wall,
            'scope': 'whole_current_mission',
            'basis': 'goal.rewards excludes starting inventory; existing measured active categories; mission start to review time',
            'unavailable': [name for name, value in [('active_rate', rate(active)), ('wall_rate', rate(wall))]
                            if value is None]}


def _farm_cohort(rows):
    measured = [r for r in rows if _number(r.get('wall_seconds'), 0.000001) and _number(r.get('retained_sp'))]
    wall = sum(r['wall_seconds'] for r in measured)
    retained = sum(r['retained_sp'] for r in measured)
    complete = bool(rows) and len(measured) == len(rows)
    drives = [r for r in measured if _number(r.get('drive_seconds'), 0.000001)
              and r['drive_seconds'] <= r['wall_seconds']]
    return {'runs': len(rows), 'wall_timing_coverage': len(measured),
            'drive_timing_coverage': len(drives), 'analytics_join_coverage': sum(r.get('analytics_joined', False) for r in rows),
            'retained_sp': retained if complete else None, 'total_wall_seconds': wall if complete else None,
            'retained_sp_hour': retained * 3600 / wall if complete and wall > 0 else None,
            'wall_seconds': percentiles(r['wall_seconds'] for r in measured),
            'drive_seconds': percentiles(r['drive_seconds'] for r in drives),
            'non_drive_wall_seconds': percentiles(r['wall_seconds'] - r['drive_seconds'] for r in drives),
            'non_drive_definition': 'total run wall minus observed drive; includes search, loading, menus, recovery and pauses',
            'sample_ids': [r.get('id') for r in rows],
            'first_recorded_start': rows[0].get('started_at') if rows else None,
            'last_recorded_end': rows[-1].get('ended_at') if rows else None,
            'optimization_versions': sorted({r.get('optimization_version') or 'legacy' for r in rows}),
            'per_run': [{k: r.get(k) for k in ('id', 'retained_sp', 'wall_seconds', 'drive_seconds', 'analytics_joined',
                                             'capped', 'partial_timing', 'run_type', 'optimization_version')} for r in rows]}


def review_farms(goal, source, trial, *, revision_at=None):
    """Diagnose Mini output using durable full-run wall cost; never decide a trial."""
    if not isinstance(trial, dict) or trial.get('goal_id') != goal.get('id') or trial.get('candidate') != MINI:
        return {'status': 'current_mini_trial_unavailable', 'comparison': {'available': False}}
    joined, conflicts = {}, set()
    for row in _rows(source.get('farms')):
        identifier = row.get('id')
        if not isinstance(identifier, str) or row.get('share_code') != MINI:
            continue
        if identifier in joined and joined[identifier] != row:
            conflicts.add(identifier)
        joined[identifier] = row
    rows, seen, duplicate_ids = [], set(), set()
    for original in _rows(trial.get('runs')):
        row = dict(original)
        identifier = row.get('id')
        if identifier in seen:
            duplicate_ids.add(identifier)
        seen.add(identifier)
        analytics = joined.get(identifier) if identifier not in conflicts else None
        row.update(analytics_joined=analytics is not None,
                   capped=bool(row.get('after_sp') == 999 or (analytics or {}).get('capped')),
                   partial_timing=analytics.get('partial_timing') if analytics else None,
                   run_type=analytics.get('run_type') if analytics else None,
                   started_at=analytics.get('started_at') if analytics else None,
                   ended_at=analytics.get('ended_at') if analytics else None)
        if analytics and row['run_type'] is None:
            row['run_type'] = ('interrupted' if row['partial_timing'] else
                               'intentional_top_up' if row.get('exit_reason') == 'intentional_target_top_up' else
                               'natural_completion' if row.get('exit_reason') == 'natural_completion' else None)
        rows.append(row)
    eligible = [r for r in rows if r.get('id') not in duplicate_ids and r['analytics_joined']
                and r['partial_timing'] is False and not r['capped'] and r['run_type'] == 'natural_completion'
                and _number(r.get('wall_seconds'), 0.000001) and _number(r.get('retained_sp'))]
    before, after, excluded = [], [], Counter()
    boundary = _stamp(revision_at) if revision_at is not None else None
    if revision_at is None:
        after, before = eligible[-3:], eligible[-6:-3]
        diagnostic_rows = eligible
    else:
        for row in eligible:
            start, end = _stamp(row.get('started_at')), _stamp(row.get('ended_at'))
            if boundary is None:
                excluded['invalid_revision_boundary'] += 1
            elif end is None or start is None or start > end:
                excluded['unknown_or_invalid_revision_times'] += 1
            elif end < boundary:
                before.append(row)
            elif start >= boundary:
                after.append(row)
            else:
                excluded['crosses_revision_boundary'] += 1
        diagnostic_rows = after
        before, after = before[-3:], after[-3:]
    latest, previous = _farm_cohort(after), _farm_cohort(before)
    mixed = len(latest['optimization_versions']) > 1 or len(previous['optimization_versions']) > 1
    comparison = len(after) >= 3 and len(before) >= 3 and not mixed
    old, new = previous['retained_sp_hour'], latest['retained_sp_hour']
    gain = 100 * (new / old - 1) if comparison and old and new is not None else None
    overall = _farm_cohort(rows)
    if duplicate_ids:
        overall['retained_sp_hour'] = None
    baseline = trial.get('baseline_sp_hour')
    baseline = baseline if _number(baseline, 0.000001) else None
    total_rate = overall['retained_sp_hour']
    return {'status': 'observing', 'trial_status': trial.get('status'),
            'scope': 'completed runs recorded by the current Mini trial',
            'open_run_id': (trial.get('open_run') or {}).get('id'),
            'baseline_code': trial.get('baseline_code'), 'frozen_mega_sp_hour': baseline,
            'baseline_runs': len(_rows(trial.get('baseline_farms'))),
            'overall_trial': overall,
            'overall_gain_vs_frozen_mega_percent': 100 * (total_rate / baseline - 1) if baseline and total_rate is not None else None,
            'last3_uncapped_complete': _farm_cohort(diagnostic_rows[-3:]),
            'last10_uncapped_complete': _farm_cohort(diagnostic_rows[-10:]),
            'capped': _farm_cohort([r for r in rows if r['capped']]),
            'partial_or_intentional': _farm_cohort([r for r in rows if r['partial_timing'] or r['run_type'] == 'intentional_top_up']),
            'unjoined': _farm_cohort([r for r in rows if not r['analytics_joined']]),
            'comparison': {'available': comparison, 'minimum_runs_each': 3, 'latest': latest, 'previous': previous,
                           'retained_sp_hour_change_percent': gain,
                           'provisional': True, 'mixed_versions': mixed,
                           'interpretation': 'Diagnostic comparison only; full trial still controls keep/revert.'},
            'coverage': {'trial_runs': len(rows), 'uncapped_complete_joined_runs': len(eligible),
                         'conflicting_analytics_ids': len(conflicts), 'duplicate_trial_ids': len(duplicate_ids)},
            'revision_excluded': dict(excluded),
            'trial_controls': {'reward_limit': trial.get('reward_limit'), 'minimum_gain_percent': trial.get('minimum_gain_percent'),
                               'decision_owned_by': 'FarmTrial.evaluate; this review never retunes or reverts'},
            'notes': ['Overall trial retains capped, partial, restart and recovery costs. Diagnostic subsets are not the keep/revert denominator.',
                      'Drive timing does not replace full wall time. Cap and partial groups can overlap.']}


def evaluate(goal, source, performance=None, *, revision_at=None, step_rows=(), now=None, farm_trial=None):
    """Compare disjoint 20-car cohorts, retaining every valid tail observation.

    Without revision_at this is a trend comparison, never a deployment claim.
    With it, the baseline ends before the boundary and every candidate cycle
    must start after it. Stages and full-cycle timing must all be present.
    A 10% P50 or P90 increase is a review flag, not proof of its cause.
    """
    now = now or datetime.now().astimezone()
    goal = goal if isinstance(goal, dict) else {}
    source = source if isinstance(source, dict) else {}
    goal_id = goal.get('id')
    matching = bool(goal_id) and source.get('goal_id') == goal_id
    data = source if matching else {}
    exclusions = Counter()
    candidates, duplicate_keys, seen = [], set(), {}
    for row in _rows(data.get('cycles')):
        key = _key(row)
        if row.get('goal_id') != goal_id:
            exclusions['other_or_missing_mission'] += 1
        elif not key or _stamp(row.get('ended_at')) is None:
            exclusions['missing_identity_or_completion_time'] += 1
        elif not _number(row.get('elapsed_seconds'), 0.000001):
            exclusions['missing_or_invalid_full_duration'] += 1
        elif not isinstance(row.get('steps'), dict) or any(not _number(row['steps'].get(s)) for s in STAGES):
            exclusions['incomplete_stage_coverage'] += 1
        elif key in seen:
            if row != seen[key]:
                duplicate_keys.add(key)
                exclusions['conflicting_duplicate_rows'] += 1
            else:
                exclusions['identical_duplicate_rows'] += 1
        else:
            seen[key] = row
    for key, row in seen.items():
        if key not in duplicate_keys:
            candidates.append(row)
    candidates.sort(key=lambda row: (_stamp(row['ended_at']), _key(row)))
    boundary = _stamp(revision_at) if revision_at is not None else None
    invalid_boundary = revision_at is not None and boundary is None
    if revision_at is None:
        latest, previous = candidates[-WINDOW:], candidates[-2 * WINDOW:-WINDOW]
    else:
        starts = _cycle_starts(step_rows, goal_id)
        before, after = [], []
        for row in candidates:
            end = _stamp(row['ended_at'])
            if invalid_boundary:
                exclusions['invalid_revision_boundary'] += 1
            elif end < boundary:
                before.append(row)
            else:
                start = starts.get(_key(row), _stamp(row.get('started_at')))
                if start is None:
                    exclusions['unknown_revision_start'] += 1
                elif start > end:
                    exclusions['invalid_cycle_time_order'] += 1
                elif start < boundary:
                    exclusions['crosses_revision_boundary'] += 1
                else:
                    after.append(row)
        latest, previous = after[-WINDOW:], before[-WINDOW:]
    current, baseline = _cohort(latest, data), _cohort(previous, data)
    enough = len(latest) == WINDOW and len(previous) == WINDOW
    changes, flags = [], []
    if enough:
        for stage in ('cycle', *STAGES):
            newer = current['cycle_seconds'] if stage == 'cycle' else current['stage_seconds'][stage]
            older = baseline['cycle_seconds'] if stage == 'cycle' else baseline['stage_seconds'][stage]
            for metric in ('p50', 'p90', 'p99'):
                old, new = older[metric], newer[metric]
                delta = 100 * (new / old - 1) if old > 0 else None
                item = {'stage': stage, 'metric': metric, 'previous_seconds': old,
                        'latest_seconds': new, 'change_percent': delta}
                changes.append(item)
                if metric in ('p50', 'p90') and delta is not None and delta >= 10 - 1e-9:
                    flags.append(dict(item, reason='observed_regression_review_required'))
    perf = performance if isinstance(performance, dict) and performance.get('goal_id') == goal_id else {}
    operations = []
    recorded_operations = perf.get('operations')
    for name, values in (recorded_operations if isinstance(recorded_operations, dict) else {}).items():
        if isinstance(values, dict) and _number(values.get('seconds')) and _number(values.get('count')):
            operations.append({'operation': name, 'recorded_seconds': values['seconds'], 'count': values['count'],
                               'recent_median_ms': values.get('recent_median_ms') if _number(values.get('recent_median_ms')) else None})
    operations.sort(key=lambda item: item['recorded_seconds'], reverse=True)
    updated = _stamp(data.get('updated_at'))
    age = _stamp(now) - updated if updated is not None else None
    return {'schema_version': 1, 'goal_id': goal_id, 'reviewed_at': now.isoformat(),
            'source_updated_at': data.get('updated_at'),
            'source_age_seconds': age if age is not None and age >= 0 else None,
            'mode': 'revision' if revision_at is not None else 'trend',
            'revision_at': revision_at.isoformat() if isinstance(revision_at, datetime) else revision_at,
            'status': ('mission_data_unavailable' if not matching else 'invalid_revision_boundary' if invalid_boundary else
                       'ready' if enough else 'collecting_full_cycles'),
            'minimum_cars_per_cohort': WINDOW, 'eligible_completed_cycles': len(candidates),
            'latest': current, 'previous': baseline,
            'comparison': {'available': enough and matching and not invalid_boundary, 'changes': changes, 'regressions': flags,
                           'interpretation': 'Observed association only. No automatic tuning or causal improvement claim.'},
            'mission_rates': _rates(goal, data, now) if matching else None,
            'farm_review': review_farms(goal, data, farm_trial, revision_at=revision_at) if matching else None,
            'excluded': dict(exclusions), 'all_valid_outliers_retained': True,
            'operation_costs': operations[:12],
            'operation_cost_scope': 'mission cumulative; recent medians are process-local; nested work may overlap; not revision deltas',
            'unavailable': ['mandatory_gameplay_time', 'causal_game_vs_automation_time'],
            'notes': ['Cycle duration is recorded active conversion time, including recorded interruptions, not an inferred wall interval.',
                      'Percentiles use the existing nearest-rank definition; with 20 cars P99 is the sample maximum.',
                      'Stage percentiles do not sum to the full-cycle percentile.',
                      'Health is unavailable when dropped telemetry cannot be localized to a cohort.']}


def _retry_locked_read(action):
    """Brief Windows checkpoint sharing violations must not erase evidence.

    Reviews run on the diagnostics stream. The bounded retry adds at most
    20ms of waiting per file, and never retries malformed or absent files.
    """
    for attempt in range(READ_ATTEMPTS):
        try:
            return action()
        except PermissionError:
            if attempt + 1 == READ_ATTEMPTS:
                raise
            time.sleep(READ_RETRY_SECONDS)


def _read_json(path, errors):
    def payload_once():
        with path.open('rb') as file:
            return file.read(MAX_JSON_BYTES + 1)
    try:
        payload = _retry_locked_read(payload_once)
        if len(payload) > MAX_JSON_BYTES:
            errors.append(f'{path.name}: exceeds bounded read size')
            return {}
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError('expected an object')
        return result
    except (OSError, ValueError) as error:
        errors.append(f'{path.name}: {type(error).__name__}')
        return {}


def _read_steps(path, errors):
    def payload_once():
        with path.open('rb') as file:
            size = file.seek(0, 2)
            file.seek(max(0, size - MAX_STEP_BYTES))
            if size > MAX_STEP_BYTES:
                file.readline()  # Discard a possibly partial first record.
            payload = file.read(MAX_STEP_BYTES)
        return size, payload
    try:
        size, payload = _retry_locked_read(payload_once)
    except OSError as error:
        errors.append(f'{path.name}: {type(error).__name__}')
        return []
    rows = []
    malformed = 0
    for line in payload.splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except (ValueError, UnicodeError):
            malformed += 1
    if malformed:
        errors.append(f'{path.name}: {malformed} incomplete or malformed records ignored')
    if size > MAX_STEP_BYTES:
        # The first retained cycle may have earlier collection attempts outside
        # this bounded tail. Its apparent start is unsafe for a revision gate.
        first_key = next((_key(row) for row in rows if _key(row)), None)
        rows = [row for row in rows if _key(row) != first_key]
        errors.append(f'{path.name}: bounded tail; first retained cycle start excluded')
    return rows


def snapshot(root=None, *, revision_at=None, now=None):
    """Read a bounded snapshot, retrying brief locks; never write or export."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1] / 'runs'
    errors = []
    goal = _read_json(root / 'goal.json', errors)
    source = _read_json(root / 'analytics.json', errors)
    performance = _read_json(root / 'performance.json', errors)
    farm_trial = _read_json(root / 'farm_trial.json', errors) if (root / 'farm_trial.json').exists() else None
    steps = _read_steps(root / 'analytics_steps.jsonl', errors) if revision_at is not None else ()
    result = evaluate(goal, source, performance, revision_at=revision_at, step_rows=steps, now=now, farm_trial=farm_trial)
    result['read_errors'] = errors
    result['primary_inputs_complete'] = (bool(goal.get('id')) and source.get('goal_id') == goal['id']
        and not any(error.startswith(('goal.json:', 'analytics.json:')) for error in errors))
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--revision-at', help='Deployment timestamp with UTC offset; excludes straddling cycles')
    args = parser.parse_args()
    print(json.dumps(snapshot(args.root, revision_at=args.revision_at), indent=2, allow_nan=False))
