"""Display-only native inventory labels; never used for gameplay decisions."""
from datetime import datetime, timezone
from .inventory import PROOF


def inventory_labels(proof, session, account, runtime, worker_pid, *, now=None):
    missing = dict(inventory_line='SAVED SW / WS: awaiting live game read',
                   inventory_read='Inventory comes only from My Horizon')
    try:
        now = now or datetime.now(timezone.utc)
        observed = datetime.fromisoformat(proof['observed_at'])
        same_account = (bool(str(account.get('gamertag', '')).strip()) and
            str(proof.get('gamertag', '')).casefold() == str(account['gamertag']).casefold())
        valid = (bool(session.get('id')) and proof.get('goal_id') == session['id']
            and proof.get('proof') == PROOF and proof.get('samples') == 2 and same_account
            and all(type(proof.get(k)) is int and proof[k] >= 0 for k in ('super_wheelspins','wheelspins'))
            and observed.tzinfo is not None and observed <= now)
        if not valid:
            return missing
        current = (proof.get('worker_pid') == runtime.get('pid') == worker_pid
            and bool(runtime.get('worker_run')) and proof.get('worker_run') == runtime['worker_run'])
        if current:
            try:
                started = datetime.fromisoformat(runtime['worker_started_at'])
                current = started.tzinfo is not None and started <= observed
            except (KeyError, ValueError, TypeError):
                current = False
        if current:
            return dict(inventory_line=f"SAVED  {proof['super_wheelspins']:,} SW  |  {proof['wheelspins']:,} WS",
                        inventory_read=f"Read {proof['observed_at']}")
        # Older worker evidence remains historical display data only. Require
        # the saved goal's account as well as the currently observed account.
        if (not str(session.get('credit_account', '')).strip() or
                str(session['credit_account']).casefold() != str(account['gamertag']).casefold()):
            return missing
        return dict(inventory_line=f"LAST VERIFIED  {proof['super_wheelspins']:,} SW  |  {proof['wheelspins']:,} WS",
                    inventory_read=f"Verified {proof['observed_at']} · current balance not reread")
    except (KeyError, TypeError, ValueError, AttributeError):
        return missing
