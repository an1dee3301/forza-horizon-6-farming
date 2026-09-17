"""Mission-scoped measurements for Discord charts; no forecasts become samples."""
import json
import math
from pathlib import Path


def number(value):
    return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)


def collect(root, goal_id):
    from .reporting import read_json
    root = Path(root)
    data = read_json(root/'analytics.json')
    if not goal_id or data.get('goal_id') != goal_id:
        data = {}
    account = []
    path = root/'account_history.jsonl'
    if path.exists():
        # Bounded tail; discard a partial first line after seeking.
        with path.open('rb') as stream:
            size = stream.seek(0,2)
            stream.seek(max(0,size-2_000_000))
            if size > 2_000_000:
                stream.readline()
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and goal_id and row.get('goal_id') == goal_id:
                        account.append(row)
                except (ValueError,TypeError):
                    continue
    cleanup = []
    cleanup_total = 0
    cleanup_path = root/'analytics_garage_cleanup.jsonl'
    if cleanup_path.exists():
        with cleanup_path.open('rb') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row,dict) and goal_id and row.get('goal_id') == goal_id:
                        count = row.get('count')
                        if type(count) is int and count > 0:
                            cleanup_total += count
                            cleanup.append(dict(row,removed_total=cleanup_total))
                except (ValueError,TypeError):
                    continue
    return dict(goal_id=goal_id, cycles=data.get('cycles', [])[-1000:],
                farms=data.get('farms', [])[-100:], refills=data.get('refills', [])[-100:],
                progress=data.get('progress_points', [])[-10000:],
                seconds=data.get('seconds', {}), account=account[-2000:],
                garage_cleanup=cleanup[-2000:],
                garage_cleanup_total=cleanup_total,
                retries=data.get('retries',0), crashes=data.get('crashes',0))


def record_account(path, account, *, credits=False, level=False):
    """Append only fields verified by this observation, retaining their times."""
    from .reporting import read_json
    root = Path(path).parent
    goal = read_json(root/'goal.json')
    if not goal.get('id'):
        return
    row = {'goal_id':goal['id'], 'event':(account.get('checkpoint') or {}).get('key')}
    for field, accepted, timestamp in [('credits',credits,'observed_at'),('level',level,'level_observed_at')]:
        if accepted:
            row[field] = account.get(field)
            row[field+'_at'] = account.get(timestamp)
    if len(row) > 2:
        with (root/'account_history.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(row)+'\n')
