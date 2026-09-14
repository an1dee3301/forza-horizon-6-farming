"""Save a verified pre-run account snapshot without counting inventory as earnings."""
from pathlib import Path
from .reporting import RUNS, read_json, write_json, now
from .ownership import WorkerLease


def save_baseline(fields, evidence, root=RUNS):
    root = Path(root)
    allowed = {'credits','level','prestige','sp','super_wheelspins','wheelspins',
               'garage_cars','collection_cars','collection_points','current_car',
               'total_winnings','races','podiums','victories','manufacturers_owned',
               'time_driven_seconds','first_place_seconds','clean_laps','clean_overtakes',
               'max_race_collisions','average_race_collisions'}
    if set(fields)-allowed or not evidence:
        raise ValueError('Baseline requires known account fields and observation evidence')
    for key,value in fields.items():
        if key != 'current_car' and (type(value) is not int or value < 0):
            raise ValueError('Account counters must be nonnegative whole numbers')
    if 'sp' in fields and fields['sp'] > 999:
        raise ValueError('SP exceeds the game cap')
    with WorkerLease():
        goal = read_json(root/'goal.json')
        if not goal.get('id') or goal.get('rewards',0) or goal.get('bought',0):
            raise RuntimeError('Starting baseline requires a fresh, unstarted mission')
        stamp = now()
        baseline = dict(goal_id=goal['id'], observed_at=stamp, fields=fields,
                        evidence=evidence, source='Verified live account observations before mission start')
        write_json(root/'account_baseline.json',baseline)
        goal['account_baseline'] = baseline
        if 'sp' in fields:
            goal.update(last_sp=fields['sp'],sp_observed_at=stamp)
        write_json(root/'goal.json',goal)
        account = read_json(root/'account_observed.json')
        account.update(fields)
        for field in fields:
            account[field+'_observed_at'] = stamp
        if 'credits' in fields:
            account['observed_at'] = stamp
        account['source'] = baseline['source']
        account['checkpoint'] = dict(key=goal['id']+':baseline', label='Starting account snapshot',
            status='Verified' if {'credits','level'} <= fields.keys() else 'Partial', verified_at=stamp)
        for field in ('credits','level'):
            if field in fields:
                account[field+'_event'] = account['checkpoint']['key']
        write_json(root/'account_observed.json',account)
        from .chart_data import record_account
        record_account(root/'account_observed.json',account,credits='credits' in fields,level='level' in fields)
        from .analytics import Tracker
        Tracker(root).event('progress',goal)
        return baseline
