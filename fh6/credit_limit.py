"""Credit-backed planning. A saved estimate never confirms a game purchase."""
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PRICE = 95_000
SOURCE = 'Two matching credit readings on the identified game account'
MAX_AGE = 120


class CreditProofUnavailable(RuntimeError):
    """Recoverable: wait for actual account proof, never interpret absence as zero."""


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def event_belongs(event, goal, cars):
    """Accept an explicit mission request or this mission's exact car session."""
    if not isinstance(event, str):
        return False
    if re.fullmatch(re.escape(str(goal['id'])) + r':credit_budget:[0-9a-f]{32}', event):
        return True
    farm = re.fullmatch(re.escape(str(goal['id'])) + r'_(\d+):\d+:farm_(prepare|search|read_sp)', event)
    if farm and int(farm[1]) in {goal.get('farm_runs', 0), goal.get('farm_runs', 0)-1}:
        return True
    if (cars.get('funding') or {}).get('goal_id') != goal['id']:
        return False
    match = re.fullmatch(re.escape(str(cars.get('id'))) + r':(\d+):(choose|return)', event)
    return bool(match and 1 <= int(match[1]) <= cars.get('completed', 0) + 1)


def pending_copy(cars, ledger):
    """Already-paid and uncertain attempts must finish their existing recovery first."""
    phase = cars.get('phase')
    if not cars or phase == 'complete':
        return False
    if phase not in {'collection', 'buy'}:
        return True
    if cars.get('bought', 0) > cars.get('completed', 0):
        return True
    record = read_json(ledger.path)
    return bool(phase == 'buy' and record.get('id') != cars.get('purchase_before')
                and record.get('id') and record.get('status') in
                {'pending', 'confirmed', 'resolved_bought'})


def committed_since(ledger, observed_at):
    """Deduct exact later receipts, including same-second timestamp uncertainty."""
    ledger.ready()
    local_cutoff = observed_at.astimezone().strftime('%Y%m%d_%H%M%S')
    purchases = set()
    directory = Path(ledger.path).parent
    for path in directory.glob('*.json'):
        if path.name == 'latest.json':
            continue
        if not re.fullmatch(r'\d{8}_\d{6}_\d{6}', path.stem):
            continue
        if path.stem[:15] < local_cutoff:
            continue
        record = read_json(path)
        if record.get('id') != path.stem or record.get('price') != PRICE:
            raise CreditProofUnavailable('Purchase ledger is incomplete; waiting for a confirmed credit budget')
        if record.get('status') in {'confirmed', 'resolved_bought'}:
            purchases.add(path.stem)
        elif record.get('status') != 'resolved_not_bought':
            raise CreditProofUnavailable('Purchase remains uncertain; credit planning cannot authorize another buy')
    # latest is authoritative during the brief gap before the per-id file write.
    latest = read_json(ledger.path)
    if latest and str(latest.get('id', ''))[:15] >= local_cutoff:
        if latest.get('price') != PRICE or not re.fullmatch(r'\d{8}_\d{6}_\d{6}', str(latest.get('id'))):
            raise CreditProofUnavailable('Latest purchase receipt is not an exact Mazda transaction')
        if latest.get('status') in {'confirmed', 'resolved_bought'}:
            purchases.add(latest['id'])
    return len(purchases)


def verified_budget(account, goal, cars, ledger, *, now=None, event=None, requested_at=None):
    """Return an estimate only from recent, identified, twice-read account credits."""
    now = now or utc_now()
    observed = timestamp(account.get('credits_observed_at'))
    checkpoint = account.get('checkpoint') or {}
    credits_event = account.get('credits_event')
    expected = goal.get('credit_account')
    credits = account.get('credits')
    if (not isinstance(expected, str) or not expected.strip()
            or str(account.get('gamertag', '')).casefold() != expected.casefold()
            or type(credits) is not int or not 0 <= credits <= 999_999_999
            or account.get('source') != SOURCE or observed is None
            or not 0 <= (now-observed).total_seconds() <= MAX_AGE
            or credits_event != checkpoint.get('key')
            or not event_belongs(credits_event, goal, cars)
            or (event is not None and credits_event != event)
            or (requested_at is not None and observed < requested_at)):
        return None
    # A truncated OCR result can be perfectly repeatable (for example,
    # 75,449,170 being read twice as 49,170).  Two matching frames alone are
    # therefore insufficient for a terminal credit decision.  Compare every
    # newer balance with the last accepted budget and the exact purchase
    # ledger.  During automation, confirmed Mad Mike purchases are the only
    # operation allowed to reduce credits; an unexplained larger drop is OCR
    # evidence failure, never proof of exhaustion.
    prior = goal.get('credit_budget') or {}
    prior_observed = timestamp(prior.get('credits_observed_at'))
    prior_credits = prior.get('observed_credits')
    if (type(prior_credits) is int and prior_credits >= 0 and
            prior_observed is not None and observed > prior_observed):
        confirmed = committed_since(ledger, prior_observed)
        if credits < max(0, prior_credits-confirmed*PRICE):
            return None
    count = committed_since(ledger, observed)
    available = max(0, credits - count*PRICE)
    return dict(goal_id=goal['id'], gamertag=account['gamertag'], observed_credits=credits,
                credits_observed_at=observed.isoformat(), credits_event=credits_event,
                source=SOURCE, purchases_after_observation=count, committed_credits=count*PRICE,
                available_credits=available, affordable_purchases=available//PRICE,
                checked_at=now.isoformat())


class CreditLimit:
    def __init__(self, path, *, now=utc_now, clock=time.monotonic, timeout=15):
        self.path, self.now, self.clock, self.timeout = Path(path), now, clock, timeout

    def budget(self, nav, goal, cars, ledger, *, force=False, full_header=False):
        nav.check()
        ledger.ready()
        proof = verified_budget(read_json(self.path), goal, cars, ledger, now=self.now())
        # Never stop on a cached low balance or on subtraction alone. Get two new
        # actual readings after the completed purchase before declaring exhaustion.
        if not force and proof and proof['affordable_purchases'] > 0:
            nav.check()
            return proof
        observer = getattr(nav, 'account_observer', None)
        if observer is None or not callable(getattr(observer, 'begin_event', None)):
            raise CreditProofUnavailable('Credit mode needs the account reader; no balance was assumed')
        event = f"{goal['id']}:credit_budget:{uuid.uuid4().hex}"
        requested = self.now().replace(microsecond=0)
        observer.begin_event(event, 'Verified credit budget')
        obs = nav.observe()
        # The compact account strip on pause repeatedly produced no usable
        # balance (68 timeouts in the current operation). At an unpaid farm
        # boundary, go straight to the full home header instead of burning the
        # entire 15-second compact-read timeout first. FarmNavigator will use
        # the direct Enter House prompt when the car is already at home.
        if full_header or getattr(obs, 'screen', None) == 'pause_menu' or not observer.visible(obs):
            # This is only called at an unpaid batch/refill boundary. Navigation
            # retains its own exact menu, sync, focus and F7 guards.
            if getattr(obs, 'screen', None) == 'pause_menu':
                nav.ensure_home()
            else:
                nav.back_home()
        deadline = self.clock() + self.timeout
        retried_header = False
        while self.clock() < deadline:
            nav.check()
            nav.observe()
            proof = verified_budget(read_json(self.path), goal, cars, ledger,
                                    now=self.now(), event=event, requested_at=requested)
            if proof and (proof['affordable_purchases'] > 0 or
                          (proof['observed_credits'] < PRICE and not proof['purchases_after_observation'])):
                nav.check()
                return proof
            nav.pause(.2)
            if self.clock() >= deadline and not retried_header:
                # A visible compact card can remain unreadable indefinitely.
                # Change to the existing home route once, retaining this event
                # and the two fresh account/credit proofs before any purchase.
                retried_header = True
                nav.emit('log', 'Compact credit read timed out; retrying from the home account header.')
                # Wake an idle garage before asking its menu recognizer to
                # navigate. Waiting for the hidden menu first cannot recover.
                nav.key('right')
                if nav.observe().screen == 'pause_menu':
                    nav.ensure_home()
                else:
                    nav.back_home()
                nav.key('right')
                deadline = self.clock() + self.timeout
        raise CreditProofUnavailable('Waiting for two fresh credit readings on the identified account; no new batch authorized')
