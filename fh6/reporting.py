"""Read-only mission reports and images. This module never sends game inputs."""
import ctypes
import io
import json
import os
from pathlib import Path
import re
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit
import uuid

from PIL import Image, ImageDraw, ImageFont
import forza_cycle as core
from .report_secrets import validate_url
from .report_theme import BG, FG, GREEN, AMBER, MUTED, GRID, BORDER


RUNS = core.BASE/'runs'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def latest_jsonl(path):
    """Read the latest complete journal row without loading the whole file."""
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0, 2)
            end = stream.tell()
            stream.seek(max(0, end-8192))
            rows = stream.read().decode('utf-8', errors='ignore').splitlines()
        return json.loads(rows[-1]) if rows else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    from .session import replace_checkpoint
    replace_checkpoint(temp, path)


def redacted(text):
    text = re.sub(r'Game focus lost \([^)]*\)', 'Game focus lost', str(text))
    return re.sub(r'https?://[^\s<>]*discord(?:app)?\.com/api/[^\s<>]+', '[private webhook]', text)[:1800]


class RuntimeFeed:
    """Small local status feed; networking and image rendering happen elsewhere."""
    def __init__(self, path=RUNS/'report_runtime.json'):
        self.path = Path(path)
        self.data = {'pid': os.getpid(), 'active': False, 'worker_started_at': now(),
                     'worker_run': uuid.uuid4().hex}

    def event(self, kind, value):
        if kind not in {'stage', 'status', 'activity', 'done', 'cancelled'}:
            return
        try:
            key = 'active' if kind in {'activity', 'done'} else kind
            value = False if kind == 'done' else value
            if self.data.get(key) == value:
                return
            stamp = now()
            if kind == 'stage':
                self.data['stage_since'] = stamp
            self.data.update({key: redacted(value) if isinstance(value, str) else value,
                              'updated_at': stamp})
            write_json(self.path, self.data)
        except OSError:
            pass  # Reporting must not stop the game worker.


class AccountObserver:
    """Update only an already identified account's twice-read credit balance."""
    def __init__(self, path=RUNS/'account_observed.json'):
        self.path = Path(path)
        self.data = read_json(path)
        self.previous = None
        self.previous_level = None
        self.previous_prestige = None
        self.last_header = 0
        self.last_persisted = 0
        self.saved_credits_event = self.data.get('credits_event')
        self.confirmation_attempts = 0

    def begin_event(self, key, label, requested_at=None):
        if (self.data.get('checkpoint') or {}).get('key') == key:
            return
        self.data['checkpoint'] = dict(key=key, label=label, requested_at=requested_at or now(),
                                       status='Waiting for account header')
        self.previous = self.previous_level = self.previous_prestige = None
        self.data.pop('credits_event', None)
        self.data.pop('level_event', None)
        self.last_header = 0
        self.confirmation_attempts = 0
        write_json(self.path, self.data)

    @property
    def needs_confirmation(self):
        checkpoint = self.data.get('checkpoint') or {}
        return bool(checkpoint and checkpoint.get('status') != 'Verified' and self.confirmation_attempts < 3)

    @staticmethod
    def visible(obs):
        return obs.screen in {'cars', 'campaign', 'home_tab', 'upgrades', 'garage_grid',
                              'challenge_browser', 'eventlab', 'pause_menu','mad_mike_mastery','car_mastery'}

    def observe(self, obs, reader=None, force=False, observed_at=None):
        tag = self.data.get('gamertag')
        if not tag or not self.visible(obs):
            self.previous = None
            self.previous_level = None
            self.previous_prestige = None
            return
        if not force and reader is not None and time.monotonic()-self.last_header < .5:
            return
        self.last_header = time.monotonic()
        def header(document):
            text = ' '.join(line.text for line in document.lines
                            if line.box[0] >= 1400 and 30 <= line.box[1] <= 80)
            return text, re.findall(r'(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)', text)

        # Reuse navigation's existing header evidence; account-only retries
        # read the small strip, never the whole screen.
        doc = obs.doc
        from .account_header import compact_header, refine_compact_header
        compact=compact_header(doc,tag)
        if not compact and reader is not None:
            compact=refine_compact_header(obs.frame,doc,tag,reader)
        if compact:
            # Coordinate normalization preserves only independently read fields.
            from .ocr import Document, Text
            lines=[Text(f"{tag} {compact['credits']:,}",(1520,40,350,25))]
            if compact['level'] is not None:lines.append(Text(str(compact['level']),(1455,42,40,25)))
            doc=Document(lines)
        text, values = header(doc)
        if reader and (tag.casefold() not in text.casefold() or len(values) != 1):
            doc = reader.refine_region(obs.frame, doc, (1405,35,490,60))
            text, values = header(doc)
            if tag.casefold() not in text.casefold() or len(values) != 1:
                import cv2
                from .ocr import Document, Text
                patch = obs.frame[35:95,1405:1895]
                enlarged = reader.read(cv2.resize(patch, None, fx=2, fy=2,
                                                  interpolation=cv2.INTER_CUBIC))
                doc = Document([Text(line.text, (round(line.box[0]/2)+1405,
                    round(line.box[1]/2)+35, round(line.box[2]/2), round(line.box[3]/2)))
                    for line in enlarged.lines])
                text, values = header(doc)
        original_text,_=header(obs.doc)
        if reader and not compact and not values and tag.casefold() in (text+' '+original_text).casefold():
            from .account_header import read_yellow_credits
            yellow=read_yellow_credits(obs.frame,reader)
            if yellow:
                from .ocr import Document, Text
                base=doc if tag.casefold() in text.casefold() else obs.doc
                doc=Document(list(base.lines)+[Text(yellow,(1750,45,130,30))])
                text,values=header(doc)
        if tag.casefold() not in text.casefold() or len(values) != 1:
            self.previous = None
            self.previous_level = None
            self.previous_prestige = None
            checkpoint = self.data.get('checkpoint')
            if checkpoint and checkpoint.get('status') != 'Account header unreadable; previous values retained':
                checkpoint['status'] = 'Account header unreadable; previous values retained'
                write_json(self.path, self.data)
            return
        credits = int(values[0].replace(',', ''))
        # Level digits occupy the tall badge row. The tiny prestige digit
        # beneath the star can share its x range but must not become a level.
        levels = [int(line.text) for line in doc.lines if
                  1450 <= line.center[0] <= 1500 and 40 <= line.center[1] <= 80
                  and 40 <= line.box[1] <= 60 and line.box[3] >= 14
                  and re.fullmatch(r'\d{1,4}', line.text) and 1 <= int(line.text) <= 2999]
        level = levels[0] if len(levels) == 1 else None
        if not levels and reader is not None and not compact:
            from .account_badge import read_level_badge
            level = read_level_badge(obs.frame, reader)
        stamp = observed_at or now()
        prestige = None
        if reader is not None and not compact:
            from .account_header import read_prestige
            prestige = read_prestige(obs.frame, reader)
        changed = False
        checkpoint = self.data.get('checkpoint') or {}
        event_key = checkpoint.get('key')
        if credits == self.previous:
            self.data.update(credits=credits, observed_at=stamp, credits_observed_at=stamp,
                source='Two matching credit readings on the identified game account')
            changed = True
            self.data['credits_event'] = event_key
        if level is not None and level == self.previous_level:
            self.data.update(level=level, level_observed_at=stamp)
            changed = True
            self.data['level_event'] = event_key
        if prestige is not None and prestige == self.previous_prestige:
            self.data.update(prestige=prestige, prestige_observed_at=stamp)
            changed = True
        self.previous_prestige = prestige
        completed_event = bool(event_key and self.data.get('credits_event') == event_key
                               and self.data.get('level_event') == event_key)
        new_event_proof = completed_event and checkpoint.get('status') != 'Verified'
        if new_event_proof:
            checkpoint.update(status='Verified', verified_at=stamp,
                              credits=self.data['credits'], level=self.data['level'])
        elif event_key and not completed_event and changed:
            checkpoint['status'] = 'Partial account reading; previous values retained for unverified fields'
        if changed:
            try:
                if (credits != getattr(self, 'saved_credits', None)
                        or self.data.get('level') != getattr(self, 'saved_level', None)
                        or (event_key and self.data.get('credits_event') == event_key
                            and event_key != self.saved_credits_event)
                        or new_event_proof or time.monotonic()-self.last_persisted >= 60):
                    write_json(self.path, self.data)
                    from .chart_data import record_account
                    record_account(self.path, self.data, credits=credits == self.previous,
                                   level=level is not None and level == self.previous_level)
                    self.saved_credits, self.saved_level = credits, self.data.get('level')
                    self.saved_credits_event = self.data.get('credits_event')
                    self.last_persisted = time.monotonic()
            except OSError:
                pass
        self.previous = credits
        self.previous_level = level


def worker_present():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenMutexW(0x00100000, False, 'Local\\FH6AutoWorker')
    if handle:
        kernel.CloseHandle(handle)
        return True
    return False


def snapshot(root=RUNS, *, active=None, game=None, note=None):
    root = Path(root)
    goal, cars = read_json(root/'goal.json'), read_json(root/'session.json')
    runtime = read_json(root/'report_runtime.json')
    account = read_json(root/'account_observed.json')
    challenge = read_json(root/'challenge.json')
    if active is None:
        active = worker_present()
    target, earned = goal.get('limit', 0), goal.get('rewards', 0)
    matched = cars.get('id') == (goal.get('batch') or {}).get('id')
    phase = cars.get('phase') if matched and goal.get('phase') == 'convert' else goal.get('phase', 'idle')
    status = runtime.get('status', 'Worker running' if active else 'Mission paused')
    if not active and runtime.get('active'):
        status = 'Worker stopped unexpectedly; checkpoint retained'
    if goal.get('credit_limited') is True and goal.get('phase') == 'complete':
        status = 'Credit-limited mission complete; checkpoint retained'
    elif goal.get('phase') == 'complete' and earned >= target > 0:
        status = 'Target complete: earned and saved'
    if note:
        status = note
    from .analytics import current as analytics_current
    try:
        analytics = analytics_current(root, goal)
    except Exception:
        analytics = {}
    from .farm_notices import active_farm
    timestamp = now()
    farm_event = active_farm(goal, challenge, runtime, active=active, timestamp=timestamp)
    from .chart_data import collect
    charts = collect(root, goal.get('id'))
    trial = read_json(root/'farm_trial.json')
    if trial.get('goal_id') != goal.get('id'):trial={}
    speed_plan = read_json(root/'speed_trial_plan.json')
    speed_trial = speed_plan.get('next_trial', {}) if speed_plan.get('goal_id') == goal.get('id') else {}
    from .target import totals
    # These report-only diagnostics use confirmed, mission-scoped records.
    # Stage/status refreshes cannot become production progress samples.
    source = read_json(root/'analytics.json')
    if not isinstance(source, dict) or not goal.get('id') or source.get('goal_id') != goal['id']:
        source = {}
    def age_seconds(value):
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            age = (datetime.fromisoformat(timestamp)-stamp).total_seconds()
            return age if age >= 0 else None
        except (TypeError, ValueError):
            return None
    from .inventory import PROOF as INVENTORY_PROOF
    inventory_record = read_json(root/'inventory_observed.json')
    inventory = None
    if not isinstance(inventory_record, dict):
        inventory_record = {}
    inventory_age = age_seconds(inventory_record.get('observed_at'))
    inventory_tag, account_tag = inventory_record.get('gamertag'), account.get('gamertag')
    inventory_keys = ('super_wheelspins','wheelspins')
    if (goal.get('id') and inventory_record.get('goal_id') == goal['id']
            and isinstance(account_tag,str) and account_tag and isinstance(inventory_tag,str)
            and inventory_tag.casefold() == account_tag.casefold()
            and inventory_record.get('proof') == INVENTORY_PROOF and inventory_record.get('samples') == 2
            and inventory_age is not None
            and all(type(inventory_record.get(key)) is int and inventory_record[key] >= 0 for key in inventory_keys)):
        started_age = age_seconds(runtime.get('worker_started_at'))
        token = runtime.get('worker_run')
        same_run = (bool(token) and token == inventory_record.get('worker_run')
                    if token else runtime.get('pid') is not None and runtime.get('pid') == inventory_record.get('worker_pid'))
        inventory = dict(**{key:inventory_record[key] for key in inventory_keys},
            observed_at=inventory_record['observed_at'],age_seconds=inventory_age,
            current_run=bool(same_run and started_age is not None and inventory_age <= started_age),
            source='verified_my_horizon',
            mission_rewards_at_observation=inventory_record.get('mission_rewards_at_observation'),
            hybrid_correction=inventory_record.get('hybrid_correction'),
            field_observed_at={key:inventory_record['observed_at'] for key in inventory_keys},
            field_age_seconds={key:inventory_age for key in inventory_keys})
        from .inventory import apply_reward_events
        inventory=apply_reward_events(inventory,earned)
        # This is a report snapshot overlay, never a write to the account or mission.
        account = dict(account)
        for key in inventory_keys:
            account[key] = inventory[key]
            account[key+'_observed_at'] = inventory_record['observed_at']
        account['super_wheelspins_source']=inventory.get('source')
        account['super_wheelspins_estimated']=inventory.get('estimated',False)
    if inventory is None:
        values, stamps, ages = {}, {}, {}
        for key in inventory_keys:
            age = age_seconds(account.get(key+'_observed_at'))
            valid = type(account.get(key)) is int and account[key] >= 0 and age is not None
            values[key] = account[key] if valid else None
            stamps[key] = account[key+'_observed_at'] if valid else None
            ages[key] = age if valid else None
        shared_stamp = stamps[inventory_keys[0]] if len(set(stamps.values())) == 1 else None
        inventory = dict(**values,observed_at=shared_stamp,age_seconds=age_seconds(shared_stamp),
            current_run=False,source='prior_account_observation',field_observed_at=stamps,field_age_seconds=ages)
    from .operations_metrics import numeric, failure_cause
    confirmed = []
    previous_earned = None
    for point in source.get('progress_points') or []:
        if not isinstance(point, dict):
            continue
        value = point.get('earned')
        if type(value) is int and value >= 0:
            age = age_seconds(point.get('at'))
            if (type(previous_earned) is int and previous_earned < value <= earned and age is not None):
                confirmed.append(dict(kind='wheelspin', delta=value-previous_earned,
                    at=point['at'], age_seconds=age))
            previous_earned = value
    for farm in source.get('farms') or []:
        if not isinstance(farm, dict):
            continue
        before, after, gain = (farm.get(k) for k in ('before_sp','after_sp','gained_sp'))
        age = age_seconds(farm.get('ended_at'))
        if (all(type(value) is int for value in (before, after, gain))
                and 0 <= before < after <= 999 and gain == after-before and age is not None):
            confirmed.append(dict(kind='sp_gain', delta=gain, at=farm['ended_at'], age_seconds=age))
    last_progress = min(confirmed, key=lambda row:row['age_seconds']) if confirmed else None
    unresolved = None
    failure = source.get('open_failure') or {}
    if not isinstance(failure, dict):
        failure = {}
    failure_age = age_seconds(failure.get('started_at'))
    if (failure and not failure.get('ended_at') and failure_age is not None
            and failure.get('goal_id', goal.get('id')) == goal.get('id')):
        message = redacted(failure.get('message', ''))
        unresolved = dict(cause=failure_cause(message, failure.get('stage', '')),
            message=message[:160], stage=failure.get('stage'), started_at=failure['started_at'],
            wall_seconds=failure_age)
    refill = None
    plan = challenge.get('refill_plan') or {}
    if (goal.get('phase') == 'farm' and goal.get('id')
            and str(challenge.get('id','')).startswith(goal['id']+'_')
            and challenge.get('phase') != 'complete' and isinstance(plan, dict) and plan):
        before = challenge.get('before_sp')
        verified_before = type(before) is int and 0 <= before <= 999
        refill = dict(mode=plan.get('mode'), target_sp=plan.get('target_sp'),
            before_sp=before if verified_before else None,
            headroom_sp=999-before if verified_before else None,
            planned_exit=plan.get('planned_exit'), planned_drive_seconds=plan.get('planned_drive_seconds'),
            deadline_basis=plan.get('deadline_basis'), estimate_only=True)
    credit_estimate = None
    if goal.get('credit_limited') is True:
        budget = goal.get('credit_budget') or {}
        if not isinstance(budget, dict):
            budget = {}
        budget_age = age_seconds(budget.get('credits_observed_at'))
        values = [budget.get(k) for k in ('observed_credits','available_credits','committed_credits','affordable_purchases')]
        budget_tag, account_tag = budget.get('gamertag'), account.get('gamertag')
        pending = max(0, goal.get('bought', 0)-earned)
        if (budget.get('goal_id') == goal.get('id') and isinstance(budget_tag, str) and budget_tag
                and isinstance(account_tag, str) and budget_tag.casefold() == account_tag.casefold()
                and budget_age is not None and all(type(v) is int and v >= 0 for v in values)
                and values[1] == max(0, values[0]-values[2]) and values[3] == values[1]//95000):
            credit_estimate = dict(affordable_new_cars=values[3], pending_cars=pending,
                total_spins=goal.get('starting_spins_counted', 0)+earned+pending+values[3],
                credits=values[0], available_credits=values[1], committed_credits=values[2],
                observed_at=budget['credits_observed_at'], age_seconds=budget_age,
                basis='committed_purchase_adjusted', estimate_only=True)
        balance = account.get('credits')
        balance_age = age_seconds(account.get('observed_at'))
        if (type(balance) is int and balance >= 0 and balance_age is not None
                and (credit_estimate is None or balance_age < credit_estimate['age_seconds'])):
            purchases = balance//95000
            credit_estimate = dict(affordable_new_cars=purchases, pending_cars=pending,
                total_spins=goal.get('starting_spins_counted', 0)+earned+pending+purchases,
                credits=balance, observed_at=account['observed_at'], age_seconds=balance_age,
                basis='last_observed_balance', estimate_only=True)
    from .inventory_history import observed_rows
    charts['inventory']=observed_rows(root,goal.get('id'),account.get('gamertag'),inventory_record)
    charts['inventory_hybrid']=(dict(super_wheelspins=inventory.get('super_wheelspins'),
        observed_at=timestamp,source=inventory.get('source'),
        verified_rewards_after_sync=inventory.get('verified_rewards_after_sync',0))
        if inventory.get('current_run') else None)
    cleanup = analytics.get('garage_cleanup') or {}
    removed = cleanup.get('removed', 0) if type(cleanup.get('removed', 0)) is int else 0
    journal_removed = latest_jsonl(root/'analytics_garage_cleanup.jsonl').get('removed_total')
    if type(journal_removed) is int and journal_removed > removed:
        cleanup['removed'] = removed = journal_removed
        analytics['garage_cleanup'] = cleanup
    bought = goal.get('bought', 0)
    processed = min(bought, earned)
    empty_bought=cleanup.get('bought_at_verified_empty', 0)
    reconciled=max(0,empty_bought-cleanup.get('removed_at_verified_empty', removed))
    actual_zero=bool(not cleanup.get('active') and not cleanup.get('error') and cleanup.get('verified_empty')
                     and bought == empty_bought)
    mad_mike_inventory = dict(
        bought=bought, processed=processed,
        removed=removed+reconciled,
        confirmed_removed=removed, reconciled_removed=reconciled,
        remaining=max(0, bought-removed-reconciled), actual_zero=actual_zero)
    return dict(**totals(goal), cycle_target_seconds=goal.get('cycle_target_seconds',55),
        credit_limited=goal.get('credit_limited') is True, credit_budget_estimate=credit_estimate,
        active_farm_share_code=(challenge.get('share_code') if goal.get('phase') == 'farm' and goal.get('id')
            and str(challenge.get('id','')).startswith(goal['id']+'_') else None),
        timestamp=timestamp, farm_event=farm_event, farm_trial=trial, speed_trial=speed_trial, goal_id=goal.get('id'), target=target, earned=earned, analytics=analytics, charts=charts,
        remaining=max(0, target-earned), percent=round(100*earned/target, 1) if target else 0,
        bought=bought, unprocessed=max(0, bought-earned), mad_mike_inventory=mad_mike_inventory,
        sp=goal.get('last_sp'), sp_observed_at=goal.get('sp_observed_at'),
        farms=goal.get('farm_runs', 0), batch_completed=cars.get('completed') if matched else None,
        batch_limit=cars.get('limit') if matched else None, phase=phase,
        stage=runtime.get('stage', phase), active=bool(active), status=redacted(status),
        stage_since=runtime.get('stage_since'), stage_age_seconds=age_seconds(runtime.get('stage_since')),
        last_confirmed_progress=last_progress, unresolved_recovery=unresolved, refill_status=refill,
        game=game, deadline=goal.get('deadline_utc'), account=account, inventory=inventory,
        sync='Waiting for full sync' if (root/'cloud_sync.json').exists() else 'No pending sync gate recorded',
        cycle_seconds=cars.get('cycle_seconds', []), active_seconds=goal.get('active_seconds', 0))


def payload(data):
    from .farm_notices import observed_time
    account = data.get('account', {})
    credits = account.get('credits')
    account_text = account.get('gamertag', 'Not yet observed')
    if credits is not None:
        account_text += f'\n{credits:,} CR (last observed)'
    if account.get('observed_at'):
        account_text += '\nCredits verified '+observed_time(account['observed_at'])
    if account.get('level') is not None:
        account_text += f"\nLevel {account['level']} · verified {observed_time(account.get('level_observed_at'))}"
    if account.get('prestige') is not None:
        account_text += (f"\nPrestige {account['prestige']} · verified {observed_time(account['prestige_observed_at'])}"
                         if account.get('prestige_observed_at') else
                         f"\nPrestige {account['prestige']} (last recorded; not refreshed)")
    for key, label in [('super_wheelspins','Super Wheelspins'),('wheelspins','Wheelspins'),('garage_cars','Garage cars')]:
        if account.get(key) is not None:
            account_text += f"\n{label}: {account[key]:,} · last read {observed_time(account.get(key+'_observed_at'))}"
    checkpoint = account.get('checkpoint') or {}
    if checkpoint:
        key = checkpoint.get('key')
        fields_current = [name for name, proof in [('credits', 'credits_event'), ('level', 'level_event')]
                          if account.get(proof) == key]
        account_text += f"\n{checkpoint.get('label', 'Account check')}: {checkpoint.get('status')}"
        missing = [name for name in ('credits', 'level') if name not in fields_current]
        if missing:
            account_text += '\nPrevious checkpoint values: '+', '.join(missing)
    required_credits = max(0, data['remaining']-data['unprocessed'])*95000
    budget_text = f"{required_credits:,} CR estimated for remaining cars"
    if credits is not None:
        budget_text += f"\n{max(0, required_credits-credits):,} CR shortfall against last verified balance"
    fields = [
        ('Total Super Wheelspin goal', f"{data.get('total_progress',data['earned'])} / {data.get('total_target',data['target'])}\n{data.get('starting_spins',0)} starting + {data['earned']} newly earned"),
        ('Mission Super Wheelspins earned', f"{data['earned']} / {data['target']} newly earned\n{data['remaining']} remaining · verified reward nodes"),
        ('Skill points', f"{data['sp'] if data['sp'] is not None else 'Unknown'} / 999\nVerified {observed_time(data.get('sp_observed_at'))}"),
        ('Cars', f"{data['bought']} purchased\n{data['unprocessed']} awaiting mastery"),
        ('Farming / batch', f"{data['farms']} completed challenge runs\n"+(f"Batch {data['batch_completed']} / {data['batch_limit']}" if data.get('batch_limit') else 'Refilling toward 999 SP')),
        ('Current step', str(data.get('stage') or data['phase'])),
        ('Game / worker', f"Game: {data.get('game') or 'not checked'}\nWorker: {'running' if data['active'] else 'stopped'}"),
        ('Account', account_text),
        ('Remaining credit budget', budget_text),
        ('Sync', data['sync']),
        ('Run window', data.get('deadline') or 'No deadline configured'),
        ('Recorded activity', f"{data.get('active_seconds', 0)/3600:.2f} active hours\n{data['bought']*95000:,} CR in confirmed Mazda purchases\n{data['earned']*21:,} SP in completed mastery paths"),
    ]
    analytics = data.get('analytics', {})
    from .report_charts import cycle_summary
    charts = data.get('charts', {})
    if charts.get('goal_id') == data.get('goal_id'):
        fields.append(('Measured car performance', cycle_summary(charts, data.get('cycle_target_seconds',55))))
        fields.append(('Measurement coverage / recovery',
            f"{len(charts.get('cycles', []))} car samples · {len(charts.get('farms', []))} farm samples\n"
            f"{len(charts.get('refills', []))} completed refills · {len(charts.get('account', []))} account observations\n"
            f"{charts.get('retries', 0)} retries · {charts.get('crashes', 0)} crashes recorded"))
    if analytics:
        op=analytics.get('operations',{})
        if op:
            from .operations_metrics import fmt
            fields.insert(0,('Verified NEW Super Wheelspins/hour',
                f"Active {fmt(op['sw_active_hour'])} / wall {fmt(op['sw_wall_hour'])}\n"
                f"Farm {fmt(op['farm_capacity'])} cars/h / conversion {fmt(op['conversion_capacity'])} cars/h\n"
                f"Bottleneck: {op['bottleneck']} / imbalance {fmt(op['imbalance_percent'])}%\n"
                f"First-pass yield {fmt(op['first_pass_yield'])}% ({op['first_pass_samples']} instrumented cars)\n"
                f"Unassigned overhead: {fmt(op['forza_tax_percent_estimated'],'%')} (polling/pacing excluded)\n"
                'Actual causal Forza share: unmeasured.'))
        fields.append(('Completion estimate', f"{analytics['eta_seconds']/3600:.1f}–{analytics['eta_upper_seconds']/3600:.1f} hours remaining\nAbout {analytics['farms_remaining']} farm runs\n{analytics['cycle_seconds']:.1f}s median per car\nEstimate only; pauses and recovery may extend it."))
    if data.get('report_kind') == 'farm_start':
        farm = data['farm_event']
        fields.insert(0, ('SP farm started', f"Mega V6 · {farm.get('share_code')}\nStarting SP: {farm.get('before_sp')} / 999\nChallenge run {data['farms']+1} · attempt {farm['attempt']}"))
        if analytics.get('sp_per_farm', 0) > 0 and isinstance(farm.get('before_sp'), int):
            import math
            runs = math.ceil(max(0,999-farm['before_sp'])/analytics['sp_per_farm'])
            fields.insert(1, ('Refill estimate', f"About {runs} challenge runs / {runs*analytics.get('farm_seconds', 0)/60:.0f} minutes to 999 SP\nThen up to 47 Mad Mikes; estimate includes this run."))
    periodic = data.get('report_kind') == 'status'
    body = {'username': 'FH6 Mission Control', 'allowed_mentions': {'parse': []},
        'embeds': [{'title': 'FH6 // MINUTE STATUS' if periodic else ('FH6 // SP FARM STARTED' if data.get('report_kind') == 'farm_start' else 'FH6 // WHEELSPIN EARNED'), 'description': data['status'],
            'color': int((GREEN if data['active'] else AMBER)[1:], 16),
            'fields': [{'name': name, 'value': value[:1024], 'inline': not periodic} for name, value in fields],
            'timestamp': data['timestamp'], 'image': {'url': 'attachment://mission.png'},
            'footer': {'text': 'Mission progress uses verified reward nodes. Inventory shows its last observation. Earlier archived rewards excluded.'}}],
        'attachments': [{'id': 0, 'filename': 'mission.png'}]}
    if periodic:
        body['content'] = (f"## FH6 · {data.get('total_progress',data['earned']):,} / {data.get('total_target',data['target']):,} Super Wheelspins\n"
            f"**{'RUNNING' if data['active'] else 'STOPPED / RECOVERY'} · {data.get('stage') or data['phase']}**")
    return body


def render(data):
    """A readable image of verified progress, without capturing other apps."""
    canvas = Image.new('RGB', (1120, 670), BG)
    draw = ImageDraw.Draw(canvas)
    font_path = Path('C:/Windows/Fonts/consola.ttf')
    def font(size):
        return ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default(size=size)
    def label(x, y, value, size=22, fill=FG):
        draw.text((x, y), str(value), font=font(size), fill=fill)
    draw.rectangle((24, 24, 1096, 646), outline=BORDER, width=2)
    label(48, 43, 'FH6 // MISSION CONTROL', 30, GREEN)
    label(48, 97, f"{data.get('total_progress',data['earned'])} / {data.get('total_target',data['target'])}", 64)
    label(560, 120, f"{data['remaining']} REMAINING", 30, AMBER)
    draw.rectangle((48, 185, 1072, 208), fill=GRID)
    percent = data.get('total_percent', data['percent'])
    if percent > 0:
        draw.rectangle((48, 185, 48+int(1024*min(100,percent)/100), 208), fill=GREEN)
    entries = [
        ('VERIFIED SP', f"{data['sp']} / 999"), ('CARS BOUGHT', data['bought']),
        ('FARM RUNS', data['farms']), ('PENDING CARS', data['unprocessed']),
    ]
    op=data.get('analytics',{}).get('operations',{})
    if op:
        from .operations_metrics import fmt
        entries=[('NEW SW / ACTIVE H',fmt(op['sw_active_hour'])),('NEW SW / WALL H',fmt(op['sw_wall_hour'])),
                 ('VERIFIED SP',f"{data['sp']} / 999"),('CARS BOUGHT',data['bought'])]
    for index, (name, value) in enumerate(entries):
        x = 48+index*258
        label(x, 235, name, 18, MUTED)
        label(x, 265, value, 33)
    account = data.get('account', {})
    label(48, 326, account.get('gamertag', 'ACCOUNT NOT YET OBSERVED'), 25)
    if account.get('credits') is not None:
        label(560, 326, f"{account['credits']:,} CR (observed)", 23)
    label(48, 357, f"LEVEL {account.get('level', '?')}  |  PRESTIGE {account.get('prestige', '?')} (last recorded)", 15, MUTED)
    label(560, 357, 'CREDITS CHECKED '+str(account.get('observed_at', 'unknown')), 14, MUTED)
    label(48, 374, 'STEP  '+str(data.get('stage') or data['phase'])[:66], 23, GREEN)
    import textwrap
    for index, line in enumerate(textwrap.wrap(data['status'], width=83)[:3]):
        label(48, 414+index*27, line, 20)
    label(48, 521, data['sync'], 19, AMBER)
    checkpoint = account.get('checkpoint') or {}
    if checkpoint:
        label(48, 495, ('ACCOUNT CHECK: '+checkpoint.get('status', 'Pending'))[:95], 16, AMBER)
    label(48, 553, f"TOTAL = {data.get('starting_spins',0)} STARTING + {data['earned']} VERIFIED NEW SPINS", 17, MUTED)
    label(48, 590, data['timestamp']+'  |  '+('RUNNING' if data['active'] else 'PAUSED'), 18, MUTED)
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class DeliveryError(RuntimeError):
    def __init__(self, message, retry_after=60, permanent=False):
        super().__init__(message)
        self.retry_after, self.permanent = retry_after, permanent


def confirmed_images(message):
    names = {a.get('filename') for a in message.get('attachments', [])}
    # Discord can consume uploaded attachments into embeds and return an empty
    # attachments list. Its resolved CDN image objects are delivery evidence.
    for embed in message.get('embeds', []):
        image = embed.get('image', {})
        url = urlsplit(image.get('url', ''))
        if url.scheme == 'https' and url.hostname in {'cdn.discordapp.com', 'media.discordapp.net'}:
            names.add(url.path.rsplit('/', 1)[-1])
    def components(rows):
        for row in rows:
            for item in row.get('items', []):
                url = urlsplit(item.get('media', {}).get('url', ''))
                if url.scheme == 'https' and url.hostname in {'cdn.discordapp.com', 'media.discordapp.net'}:
                    names.add(url.path.rsplit('/', 1)[-1])
            components(row.get('components', []))
    components(message.get('components', []))
    return names


def send(url, data, *, opener=None, game_image=None):
    """Confirmed multipart delivery. No webhook URL or remote body enters logs."""
    url = validate_url(url)
    boundary = 'fh6-'+uuid.uuid4().hex
    message_payload = payload(data)
    periodic = data.get('report_kind') == 'status'
    if periodic:
        from .report_boards import render_boards, summary_lines, account_summary
        boards = render_boards(data, game_image)
        files = [(name, blob, 'image/png') for name,blob,title in boards]
        first = message_payload['embeds'][0]
        message_payload['attachments'] = [{'id':i,'filename':name} for i,(name,blob,title) in enumerate(boards)]
        gallery = [{'media':{'url':'attachment://'+name}, 'description':f'{i+1}/3: {title}'}
                   for i,(name,blob,title) in enumerate(boards)]
        if game_image:
            files.append(('game.jpg', game_image[0], 'image/jpeg'))
            message_payload['attachments'].append({'id':len(files)-1,'filename':'game.jpg'})
            gallery.append({'media':{'url':'attachment://game.jpg'},
                            'description':'My Horizon / Return Home · captured '+game_image[1]})
        message_payload.pop('content', None)
        from .report_status import status_text
        text_body = status_text(data)
        message_payload.pop('embeds')
        message_payload['flags'] = 1 << 15
        message_payload['components'] = [{'type':17, 'accent_color':first['color'], 'components':[
            {'type':10, 'content':text_body},
            {'type':12, 'items':gallery},
            {'type':10, 'content':'-# '+
             ('My Horizon captured '+game_image[1]+'.' if game_image else 'Waiting for a verified My Horizon / Return Home screenshot.')}]}]
        from .account_header import latest_strip
        strip = latest_strip(game_image,data)
        if strip:
            files.append(('account_strip.png',strip[0],'image/png'))
            message_payload['attachments'].append({'id':len(files)-1,'filename':'account_strip.png'})
            message_payload['components'][0]['components'].insert(0, {'type':12,'items':[
                {'media':{'url':'attachment://account_strip.png'},
                 'description':'Account / level / prestige / credits · captured '+strip[1]+' · not live'}]})
    else:
        files = [('mission.png', render(data), 'image/png')]
    if game_image and not periodic:
        files.append(('game.jpg', game_image[0], 'image/jpeg'))
        message_payload['attachments'].append({'id': 1, 'filename': 'game.jpg'})
        message_payload['embeds'].append({'title': 'My Horizon / Return Home',
            'description': 'Captured '+game_image[1]+' · Verified menu capture; not a live view.',
            'image': {'url': 'attachment://game.jpg'}})
    if 'charts' in data and not periodic:
        from .report_charts import render_charts
        for filename, png, title in render_charts(data, focused=data.get('report_kind') == 'status'):
            message_payload['attachments'].append({'id': len(files), 'filename': filename})
            message_payload['embeds'].append({'title': title,
                'description': 'Verified current-mission measurements. Empty panels indicate missing observations.',
                'image': {'url': 'attachment://'+filename}})
            files.append((filename, png, 'image/png'))
    content = json.dumps(message_payload, ensure_ascii=False).encode('utf-8')
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode()+content+
        b'\r\n')
    for index, (filename, image_bytes, mime) in enumerate(files):
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="files[{index}]"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
                 +image_bytes+b'\r\n')
    body += f'--{boundary}--\r\n'.encode()
    request = Request(url+('?wait=true&with_components=true' if periodic else '?wait=true'), data=body, method='POST',
        headers={'Content-Type': 'multipart/form-data; boundary='+boundary, 'User-Agent': 'FH6-Mission-Control/1.0'})
    opener = opener or build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=12) as response:
            message = json.loads(response.read(1_000_000))
            expected_files = {a['filename'] for a in message_payload['attachments']}
            if not message.get('id') or not expected_files <= confirmed_images(message):
                write_json(RUNS/'discord_response_check.json', {
                    'message_id': message.get('id'), 'channel_id': message.get('channel_id'),
                    'attachment_count': len(message.get('attachments', [])),
                    'attachment_names': [a.get('filename') for a in message.get('attachments', [])],
                    'embed_count': len(message.get('embeds', [])),
                    'keys': list(message), 'checked_at': now()})
                raise DeliveryError('Discord did not confirm all report images')
            return {'message_id': message['id'], 'channel_id': message.get('channel_id'),
                    'sent_at': now(), 'earned': data['earned'], 'goal_id': data['goal_id'],
                    'image_names': sorted(expected_files),
                    'container_count':sum(c.get('type')==17 for c in message.get('components',[])),
                    'gallery_items':sum(len(c.get('items',[])) for p in message.get('components',[])
                                        for c in p.get('components',[]) if c.get('type')==12)}
    except HTTPError as exc:
        if exc.code == 429:
            try:
                retry = float(json.loads(exc.read(4096)).get('retry_after', 60))
                retry = max(1, min(3600, retry))
            except (ValueError, TypeError):
                retry = 60
            raise DeliveryError('Discord rate limit; report will retry later', retry_after=retry) from None
        raise DeliveryError(f'Discord rejected the report (HTTP {exc.code})',
                            permanent=exc.code in {400,401,403,404}) from None
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError('Discord delivery could not be confirmed; a later report will contain current progress') from None


def report_due(old, current, elapsed, interval, milestone=10):
    # A reset, elapsed time, crash, farm result or changed target is not a
    # newly earned wheelspin. The first reward of a new mission starts at 0.
    baseline = old.get('earned', 0) if old and old.get('goal_id') == current.get('goal_id') else 0
    return current.get('earned', 0) > baseline
