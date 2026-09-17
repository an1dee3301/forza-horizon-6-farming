"""Archive a user-ended mission and prepare a fresh target without game inputs."""
import json
import shutil
from datetime import datetime

import forza_cycle as core
from .ownership import WorkerLease
from .session import Session
from .production import GoalSession


def reset_target(target, deadline_utc=None):
    from .budget import whole_number
    target = whole_number(target, 'Wheelspin target')
    if not 1 <= target <= 10000:
        raise ValueError('Wheelspin target must be between 1 and 10,000')
    with WorkerLease():
        core.PurchaseLedger().ready()
        cars = Session()
        if cars.data and cars.data.get('phase') != 'complete':
            raise RuntimeError('Finish the saved purchased car before resetting the target')
        root = core.BASE/'runs'
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        archive = root/'mission_archives'/stamp
        archive.mkdir(parents=True)
        for name in ('goal.json', 'session.json', 'challenge.json', 'analytics.json',
                     'account_observed.json', 'account_history.jsonl', 'sub55-benchmark.json',
                     'discord_delivery.json', 'discord_farm_delivery.json',
                     'analytics_events.jsonl', 'analytics_cycles.jsonl',
                     'analytics_steps.jsonl', 'analytics_farms.jsonl', 'analytics_refills.jsonl'):
            source = root/name
            if source.exists():
                shutil.copy2(source, archive/name)
        goal = GoalSession(root/'goal.json')
        goal.end()
        challenge = root/'challenge.json'
        if challenge.exists():
            data = json.loads(challenge.read_text(encoding='utf-8'))
            data.update(phase='complete', end_reason='user_requested_fresh_mission',
                        interrupted=True)
            temp = challenge.with_suffix('.tmp')
            temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            temp.replace(challenge)
        # The archived credit-limited mission must not intercept a fresh start.
        goal.data.pop('credit_limited', None)
        goal.start_goal(target)
        goal.save(original_deadline_utc=deadline_utc, baseline_rewards=0,
                  reset_archive=str(archive), end_at_deadline=False, run_until_target=True)
        goal.pause()
        # Reset measurements immediately, even while the panel remains paused.
        # Historical timings may inform forecasts, but are never new-run charts.
        from .analytics import Tracker, read, save
        prior = read(archive/'analytics.json')
        tracker = Tracker(root)
        tracker.event('progress', goal.data)
        tracker.data.update(prior_cycles=[r['elapsed_seconds'] for r in prior.get('cycles', [])[-20:]],
                            prior_farm_seconds=prior.get('farm_seconds', [])[-20:],
                            prior_farm_yields=prior.get('farm_yields', [])[-20:],
                            prior_source=str(archive))
        save(root/'analytics.json', tracker.data)
        from .reporting import write_json
        write_json(root/'report_runtime.json', dict(active=False, pid=None,
            status='Fresh mission ready — press F6 to start', stage='inspect_sp',
            updated_at=datetime.now().astimezone().isoformat(timespec='seconds')))
        return goal.data
