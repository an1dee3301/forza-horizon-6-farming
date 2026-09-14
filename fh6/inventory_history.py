"""Actual saved-spin observations, independent of mission reward counters."""
from datetime import datetime, timezone
from pathlib import Path


def observed_rows(root, goal_id, gamertag, current=None):
    from .reporting import read_json
    from .inventory import PROOF
    saved=read_json(Path(root)/'inventory_history.json')
    rows=list(saved.get('observations',[])) if isinstance(saved,dict) else []
    if current is not None:rows.append(current)
    accepted={}
    for row in rows:
        if not isinstance(row,dict):continue
        if (not goal_id or row.get('goal_id')!=goal_id or not gamertag or
                str(row.get('gamertag','')).casefold()!=gamertag.casefold() or
                row.get('proof')!=PROOF or row.get('samples')!=2 or
                any(type(row.get(k)) is not int or row[k]<0 for k in ('super_wheelspins','wheelspins'))):continue
        try:
            stamp=datetime.fromisoformat(row['observed_at'])
            if stamp.tzinfo is None or stamp>datetime.now(timezone.utc):continue
        except (KeyError,TypeError,ValueError):continue
        accepted[stamp.timestamp()]=row
    return [accepted[key] for key in sorted(accepted)][-10000:]


def remember(root, data):
    from .reporting import read_json, write_json
    from .inventory import inventory_summary
    if not inventory_summary(data)['current_run']:return
    root=Path(root);proof=read_json(root/'inventory_observed.json')
    if proof.get('observed_at')!=data['inventory'].get('observed_at'):return
    rows=observed_rows(root,data.get('goal_id'),(data.get('account') or {}).get('gamertag'),proof)
    path=root/'inventory_history.json'
    previous=read_json(path)
    if rows and rows!=previous.get('observations'):
        write_json(path,{'observations':rows})
