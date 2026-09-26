"""Exact Super Wheelspin targets across farming and crash-resumable car cycles.

Game actions live in the challenge and car modules. Absolute batch counters make
replaying a checkpoint harmless, including a stop after the last mastery claim.
"""
from .budget import whole_number, POINTS_PER_CAR
from .pipeline import Pipeline
from .session import Session
from .batching import funded_cars, starting_balance_allowed
from .refill_policy import refill_target
from datetime import datetime
import time

MODE = 'Earn saved Super Wheelspins'


class GoalSession(Session):
    def start_goal(self, target, reserve=0):
        reserve = whole_number(reserve, 'SP to keep')
        if self.data.get('credit_limited') is True:
            if reserve != self.data.get('reserve_sp', 0):
                raise ValueError('Resume with the saved SP reserve')
            if self.data.get('phase') != 'complete':
                # GUI target is an estimate in this mode, not a completion gate.
                super().start(MODE, self.data['limit'])
                if self.data.get('cleanup_policy') == 'final_only':
                    from .credit_stop_floor import configure_cleanup
                    configure_cleanup(self)
            return
        target = whole_number(target, 'Super Wheelspin target')
        if not 1 <= target <= 10000:
            raise ValueError('Choose a target from 1 to 10,000 Super Wheelspins')
        if reserve > 978:
            raise ValueError('SP to keep must be 978 or less, leaving room for one car')
        if self.data and self.data.get('phase') != 'complete':
            if target != self.data['limit'] or reserve != self.data.get('reserve_sp', 0):
                raise ValueError('Resume with the saved wheelspin target and SP reserve')
            super().start(MODE, target)
            return
        super().start(MODE, target)
        self.save(phase='inspect_sp', reserve_sp=reserve, batch=None, farm_runs=0, last_sp=None)


class Production:
    def __init__(self, nav, ledger, goal, car_session, challenge, emit=lambda *a: None,
                 pipeline_factory=Pipeline, credit_budgeter=None, terminal_cleaner=None):
        self.nav, self.ledger, self.goal, self.cars = nav, ledger, goal, car_session
        self.challenge, self.emit, self.pipeline_factory = challenge, emit, pipeline_factory
        self.credit_budgeter = credit_budgeter
        self.terminal_cleaner = terminal_cleaner
        self._farm_trial = None

    def boundary(self, name, action):
        """Measure control-plane work without doing analytics on the input thread."""
        identifier=f"{self.goal.data.get('id','goal')}:{name}:{time.monotonic_ns()}"
        detail=dict(id=identifier,name=name,goal_id=self.goal.data.get('id'),
                    phase=self.goal.data.get('phase'))
        self.emit('boundary_started',detail)
        try:
            result=action()
        except Exception:
            self.emit('boundary_completed',dict(detail,success=False))
            raise
        self.emit('boundary_completed',dict(detail,success=True))
        return result

    @property
    def farm_trial(self):
        # The trial record is control policy at farm boundaries.  Cache it so
        # each car-stage checkpoint does not reread the analytics file.
        if self._farm_trial is None:
            from .farm_trial import FarmTrial
            self._farm_trial = FarmTrial(self.goal.path.parent)
        return self._farm_trial

    @property
    def credit_limited(self):
        return self.goal.data.get('credit_limited') is True

    def credit_budget(self, *, force=False, full_header=False):
        from .credit_limit import CreditLimit
        if self.credit_budgeter is None:
            self.credit_budgeter = CreditLimit(self.goal.path.parent/'account_observed.json')
        proof = self.boundary('credit_check',lambda:
            self.credit_budgeter.budget(self.nav, self.goal.data, self.cars.data, self.ledger,
                                        force=force, full_header=full_header))
        from .credit_stop_floor import apply as apply_credit_floor
        proof = apply_credit_floor(self.goal.data, proof)
        self.goal.save(credit_budget=proof,
                       limit=self.goal.data['rewards'] + proof['affordable_purchases'])
        return proof

    def refresh_inventory(self, *, stay_pause=False):
        from .inventory_route import refresh_inventory
        return self.boundary('inventory_sync',lambda:
            refresh_inventory(self.nav, self.goal.data, stay_pause=stay_pause))

    def intermediate_mega_refill(self, challenge_data):
        """True after a completed Mega run when another farm run is still required."""
        g=self.goal.data
        if g.get('rewards', 0) != g.get('challenge_sp_rewards', 0):
            return False
        if (g.get('phase') not in {'inspect_sp','farm'} or not isinstance(challenge_data,dict)
                or challenge_data.get('phase')!='complete'
                or challenge_data.get('share_code')!='155439962'
                or challenge_data.get('id')!=f"{g.get('id')}_{g.get('farm_runs',0)-1}"):
            return False
        points=g.get('last_sp')
        if type(points) is not int or not 0<=points<=999:
            return False
        target=refill_target(g['limit']-g['rewards'],g['reserve_sp'])
        from .refill_control import decision_from_files
        policy=decision_from_files(points,target,self.goal.path.parent,
            self.challenge.profile,reserve=g['reserve_sp'],check=self.nav.check)
        return points<target and policy.get('mode')!='convert'

    def completed_challenge_sp(self, challenge_data):
        """Reuse the challenge module's already twice-read post-run SP proof."""
        g=self.goal.data
        if g.get('rewards', 0) != g.get('challenge_sp_rewards', 0):
            return None
        if (not isinstance(challenge_data,dict)
                or challenge_data.get('phase')!='complete'
                or challenge_data.get('id')!=f"{g.get('id')}_{g.get('farm_runs',0)-1}"):
            return None
        points=challenge_data.get('after_sp')
        return points if type(points) is int and 0<=points<=999 and points==g.get('last_sp') else None

    def mastery_balance_handoff(self):
        """True while a verified SP read is handing directly to the farm route.

        ``available_sp`` deliberately finishes on the current car's mastery
        tree.  Inventory and credit checks cannot safely navigate from that
        screen, and neither is needed before farming: the inventory read is a
        reporting correction, while the credit gate runs again immediately
        before the next unpaid purchase.  Let the farm route leave the tree in
        its normal setup sequence instead of entering a retry loop here.
        """
        last=getattr(self.nav,'last',None)
        # A completed conversion batch also leaves the final car on this
        # screen while the goal checkpoint is ``inspect_sp``. A worker reload
        # at that exact unpaid boundary must be allowed to read the visible SP
        # balance and continue into farming; inventory and credit are still
        # refreshed before the next purchase.
        return (self.goal.data.get('phase') in {'inspect_sp','farm'} and
                getattr(last,'screen',None) in {'mad_mike_mastery','car_mastery'})

    def finish_credit_limit(self, proof):
        from .credit_limit import PRICE, SOURCE, CreditProofUnavailable, pending_copy
        self.nav.check()
        self.ledger.ready()
        from .credit_stop_floor import floor_for, apply as apply_credit_floor
        floor = floor_for(self.goal.data)
        if floor is not None:
            proof = apply_credit_floor(self.goal.data, proof)
            if proof['affordable_purchases'] or pending_copy(self.cars.data, self.ledger):
                raise RuntimeError('Credit floor shutdown requires the paid car to finish first')
            # Projection is a purchase ceiling, not final native balance proof.
            # A failed fresh read leaves the ceiling in force and no new work.
            proof = self.credit_budget(force=True, full_header=True)
            if proof.get('receipt_projection'):
                raise CreditProofUnavailable('Fresh credit proof required before credit reserve shutdown')
            if proof['affordable_purchases']:
                return
            self.goal.save(phase='garage_cleanup', completed=self.goal.data['rewards'],
                           end_reason='credit_stop_floor', credit_budget=proof,
                           credit_stop_proof=proof, limit=self.goal.data['rewards'],
                           batch=None, reservation=None, final_top_up=False)
            self.emit('status', f'Credit reserve protected at {floor:,} CR; removing all Mad Mike cars before stopping')
            return
        if (proof['observed_credits'] >= PRICE or proof['purchases_after_observation']
                or pending_copy(self.cars.data, self.ledger)):
            raise RuntimeError('Credit exhaustion has not been confirmed; no completion inferred')
        # Terminal exhaustion needs three separately keyed fresh reads.  The
        # two extra reads force the full account header route, while
        # verified_budget independently checks the exact purchase ledger
        # against the previously accepted balance.  A stable OCR truncation
        # therefore cannot terminate the mission.
        confirmations = [proof]
        for _ in range(2):
            confirmations.append(self.credit_budget(force=True, full_header=True))
        if (any(p.get('observed_credits') != proof['observed_credits'] or
                p.get('observed_credits', PRICE) >= PRICE or
                p.get('purchases_after_observation') or p.get('source') != SOURCE
                for p in confirmations) or
                len({p.get('credits_event') for p in confirmations}) != 3 or
                None in {p.get('credits_event') for p in confirmations}):
            raise CreditProofUnavailable(
                'Three independent full-header credit checks did not agree; mission remains active')
        proof = dict(confirmations[-1], terminal_confirmation_count=3,
                     terminal_confirmation_events=[p['credits_event'] for p in confirmations])
        self.goal.save(phase='terminal_sp_topup', completed=self.goal.data['rewards'],
                       end_reason='insufficient_credits', credit_budget=proof,
                       limit=self.goal.data['rewards'], batch=None, reservation=None)
        self.emit('status', f"Credit limit reached — {proof['observed_credits']:,} CR remain; topping SP up to 999 before final cleanup")

    def terminal_sp_topup(self):
        """Reach a verified 999 SP after the last paid car, then allow cleanup.

        This is a crash-resumable terminal phase.  It never authorizes another
        purchase and retains the normal challenge identity/checkpoint rules.
        """
        self.nav.check()
        run_number = self.goal.data.get('terminal_sp_runs', 0)
        if type(run_number) is not int or run_number < 0:
            raise RuntimeError('Terminal SP top-up checkpoint is invalid')
        identifier = f"{self.goal.data['id']}_terminal_sp_{run_number}"
        saved = getattr(self.challenge, 'data', {})
        resumable = (isinstance(saved, dict) and saved.get('id') == identifier
                     and saved.get('phase') not in {None, 'complete'})
        completed = (isinstance(saved, dict) and saved.get('id') == identifier
                     and saved.get('phase') == 'complete'
                     and type(saved.get('after_sp')) is int)
        if completed:
            points = saved['after_sp']
            self.emit('log', f'Reusing terminal challenge exit SP proof ({points}).')
        elif resumable:
            points = None
        else:
            points = self.boundary('terminal_sp_read', self.nav.available_sp)
        if points == 999:
            self.goal.save(phase='garage_cleanup', last_sp=999,
                           terminal_sp_completed_at=datetime.now().isoformat(timespec='seconds'))
            self.emit('status', 'Terminal reserve verified at 999 SP; removing all Mad Mike cars')
            return
        if points is not None and (type(points) is not int or not 0 <= points < 999):
            raise RuntimeError('Terminal SP balance is invalid; cleanup remains blocked')
        self.emit('stage', 'terminal_sp_topup')
        self.emit('status', f'Terminal SP top-up — {points if points is not None else "resuming"}/999 verified')
        self.challenge.target_sp = 999
        self.challenge.reserve_sp = 0
        self.challenge.force_target_sp = True
        try:
            points = self.challenge.run(identifier, return_collection=False)
        finally:
            self.challenge.force_target_sp = False
        if type(points) is not int or not 0 <= points <= 999:
            raise RuntimeError('Terminal challenge returned no valid SP proof')
        changes = dict(last_sp=points, sp_observed_at=datetime.now().isoformat(timespec='seconds'))
        if not completed:
            changes.update(farm_runs=self.goal.data.get('farm_runs', 0)+1,
                           terminal_sp_runs=run_number+1)
        if points == 999:
            changes.update(phase='garage_cleanup',
                           terminal_sp_completed_at=datetime.now().isoformat(timespec='seconds'))
            self.emit('status', 'Terminal reserve verified at 999 SP; removing all Mad Mike cars')
        self.goal.save(**changes)

    def cleanup_credit_limit(self):
        """Remove every Mad Mike after the final affordable conversion."""
        self.nav.check()
        if self.terminal_cleaner is not None:
            removed = self.boundary('terminal_garage_cleanup',
                                    lambda: self.terminal_cleaner(self.nav, self.emit))
        else:
            from .analytics import Tracker
            from .garage_cleanup import GarageCleanup
            from .mad_mike_inventory import prepare_filter
            prepare_filter(self.nav)
            removed = self.boundary('terminal_garage_cleanup', lambda:
                GarageCleanup(self.nav, Tracker(), emit=self.emit).run(reset_filter_state=True))
        self.goal.save(phase='complete', completed=self.goal.data['rewards'])
        reason = 'Credit reserve protected' if self.goal.data.get('end_reason') == 'credit_stop_floor' else 'Credit limit reached'
        self.emit('status', f'{reason}; garage verified empty after removing {removed:,} Mad Mike cars in the final pass')
        self.progress()

    def cleanup_periodic(self):
        """Keep the cleanup checkpoint pending until the garage is verified empty."""
        from .credit_limit import pending_copy
        self.nav.check()
        self.ledger.ready()
        if self.goal.data.get('batch') or pending_copy(self.cars.data, self.ledger):
            raise RuntimeError('Periodic cleanup cannot remove an unfinished purchased copy')
        if self.terminal_cleaner is None:
            raise RuntimeError('Periodic cleanup requires the verified garage cleanup module')
        self.emit('stage', 'garage_cleanup')
        self.emit('status', 'Cleanup threshold reached — removing processed Mad Mike cars')
        removed = self.boundary('periodic_garage_cleanup',
            lambda: self.terminal_cleaner(self.nav, self.emit))
        self.goal.save(phase='inspect_sp', batches_since_cleanup=0,
            cleanup_rewards_baseline=self.goal.data['rewards'],
            periodic_cleanups=self.goal.data.get('periodic_cleanups', 0)+1,
            last_cleanup_removed=removed)
        self.progress()

    def progress(self):
        images = getattr(self.nav, 'report_images', None)
        if images is not None:
            images.request_reward(self.goal.data['id'], self.goal.data.get('rewards', 0))
        self.emit('progress', dict(self.goal.data))

    def bind(self, cycles=1):
        data, saved = self.goal.data, self.cars.data
        if saved['mode'] != 'Full pipeline':
            raise RuntimeError('Finish or end the saved Buy-only session before starting a wheelspin target')
        # Rewards already recorded before this goal are never counted toward it.
        self.goal.save(phase='convert', reservation=None, batch=dict(id=saved['id'], cycles=cycles,
            rewards_start=saved.get('rewards', 0), bought_start=saved.get('bought', 0),
            completed_start=saved.get('completed', 0), rewards_seen=0, bought_seen=0))

    def sync(self):
        batch, saved = self.goal.data.get('batch'), self.cars.data
        if not batch:
            return
        if saved.get('id') != batch['id']:
            raise RuntimeError('The saved car cycle changed; no purchase or reward count was guessed')
        rewards = saved.get('rewards', 0) - batch['rewards_start']
        bought = saved.get('bought', 0) - batch['bought_start']
        if rewards < batch['rewards_seen'] or bought < batch['bought_seen']:
            raise RuntimeError('The saved car counters moved backwards')
        updated = dict(batch, rewards_seen=rewards, bought_seen=bought)
        total = self.goal.data['rewards']+rewards-batch['rewards_seen']
        if total > self.goal.data['limit'] and not self.credit_limited:
            raise RuntimeError('The car batch exceeds the remaining wheelspin target')
        changes = dict(batch=updated,
            rewards=self.goal.data['rewards']+rewards-batch['rewards_seen'],
            bought=self.goal.data['bought']+bought-batch['bought_seen'],
            completed=self.goal.data['rewards']+rewards-batch['rewards_seen'])
        if 'observed_sp' in saved:
            changes.update(last_sp=saved['observed_sp'], sp_observed_at=saved.get('sp_observed_at'))
        if self.credit_limited and total > self.goal.data['limit']:
            # An already-paid car still finishes if a previous estimate was lower.
            changes['limit'] = total
        self.goal.save(**changes)
        self.farm_trial.evaluate(self.goal.data)
        self.progress()

    def car_event(self, kind, value):
        if kind == 'progress':
            self.sync()
        elif kind == 'stage':
            self.emit('stage', value)
            self.emit('status', f'Converting SP to saved Super Wheelspins — {value.replace("_", " ")}')
        else:
            self.emit(kind, value)

    def convert(self):
        self.sync()
        batch = self.goal.data['batch']
        # Legacy one-car bindings retain their original boundary on upgrade.
        stop_at = batch['completed_start'] + batch.get('cycles', 1)
        left = stop_at - self.cars.data['completed']
        proof = None
        from .credit_limit import pending_copy
        inventory_account = getattr(getattr(self.nav, 'account_observer', None), 'gamertag', None)
        if (left > 0 and isinstance(inventory_account, str) and inventory_account
                and not pending_copy(self.cars.data, self.ledger)):
            self.ledger.ready()
            self.refresh_inventory()
        pending = self.credit_limited and left > 0 and pending_copy(self.cars.data, self.ledger)
        try:
            if pending:
                # Complete the exact paid copy first. Then continue the same
                # funded batch after a fresh credit gate instead of discarding
                # the remaining SP and launching another refill.
                self.cars.start(self.cars.data['mode'], self.cars.data['limit'])
                self.pipeline_factory(self.nav, self.ledger, self.cars,
                                      self.car_event).run(max_cycles=1)
                self.sync()
                self.cars.pause()
                left = stop_at - self.cars.data['completed']
            if self.credit_limited and left > 0:
                proof = self.credit_budget()
                left = min(left, proof['affordable_purchases'])
            if left > 0:
                self.cars.start(self.cars.data['mode'], self.cars.data['limit'])
                self.pipeline_factory(self.nav, self.ledger, self.cars, self.car_event).run(max_cycles=left)
        finally:
            self.sync()
            self.cars.pause()
        unpaid_zero = proof is not None and not proof['affordable_purchases']
        if self.cars.data['phase'] not in ({'collection', 'complete', 'buy'} if unpaid_zero else {'collection', 'complete'}):
            raise RuntimeError('The purchased car has not returned to Car Collection')
        # An older multi-car run is transferred only at a completed cycle boundary.
        # The new goal owns the remaining target; the old history is retained.
        if self.cars.data['phase'] != 'complete':
            self.cars.save(phase='complete', end_reason='transferred_to_wheelspin_goal')
        batches = self.goal.data.get('batches_since_cleanup', 0)
        if self.cars.data['completed'] >= stop_at:
            batches += 1
        interval = self.goal.data.get('cleanup_every_batches', 0)
        cleanup_due = type(interval) is int and interval > 0 and batches >= interval
        car_interval = self.goal.data.get('cleanup_every_cars', 0)
        if type(car_interval) is int and car_interval > 0:
            cleanup_due = (self.goal.data['rewards'] -
                self.goal.data.get('cleanup_rewards_baseline', 0)) >= car_interval
        if self.goal.data.get('cleanup_policy') == 'final_only':
            cleanup_due = False
        self.goal.save(phase='periodic_cleanup' if cleanup_due else 'inspect_sp',
                       batches_since_cleanup=batches, batch=None,
                       completed=self.goal.data['rewards'])
        from .credit_stop_floor import floor_for
        if floor_for(self.goal.data) is not None:
            # Recount committed receipts after this capped batch, before any farm.
            proof = self.credit_budget()
            unpaid_zero = not proof['affordable_purchases']
        if unpaid_zero:
            self.finish_credit_limit(proof)

    def run(self):
        g = self.goal
        from .credit_stop_floor import floor_for
        floor_for(g.data)
        if g.data.get('phase') == 'complete' and g.data.get('end_reason') == 'credit_stop_floor':
            return
        # A terminal SP challenge can award credits after the three low-credit
        # checks that started shutdown.  Reopening a completed credit mission
        # is allowed only after a fresh full-header proof shows that another
        # exact 95,000-CR Mazda is now affordable.  This prevents both a stale
        # low OCR stop and silently leaving newly awarded credits unused.
        if (self.credit_limited and g.data.get('phase') == 'complete'
                and g.data.get('end_reason') == 'insufficient_credits'):
            proof = self.credit_budget(force=True, full_header=True)
            if proof['affordable_purchases']:
                g.save(phase='inspect_sp', batch=None, reservation=None,
                       credit_budget=proof,
                       limit=g.data['rewards'] + proof['affordable_purchases'],
                       reopened_after_credit_gain_at=datetime.now().isoformat(timespec='seconds'))
                self.emit('status',
                    f"Fresh credits fund {proof['affordable_purchases']} more Mazda; resuming production")
            else:
                return
        while g.data['phase'] != 'complete':
            self.nav.check()
            self.progress()
            if g.data['phase'] == 'periodic_cleanup':
                self.cleanup_periodic()
                continue
            if g.data['phase'] == 'terminal_sp_topup':
                self.terminal_sp_topup()
                continue
            if g.data['phase'] == 'garage_cleanup':
                self.cleanup_credit_limit()
                continue
            if g.data.get('batch'):
                self.convert()
                continue
            if not self.credit_limited and g.data['rewards'] >= g.data['limit']:
                self.nav.return_collection()
                g.save(phase='complete', completed=g.data['rewards'])
                break
            if g.data.get('reservation'):
                self.resume_reservation()
                continue
            if self.cars.data and self.cars.data.get('phase') != 'complete':
                self.bind()
                continue
            self.ledger.ready()
            challenge_data = getattr(self.challenge, 'data', {})
            farm_in_progress = (g.data['phase'] == 'farm' and isinstance(challenge_data, dict)
                and challenge_data.get('id') == f"{g.data['id']}_{g.data['farm_runs']}"
                and challenge_data.get('phase') not in {None, 'complete'})
            intermediate_refill=self.intermediate_mega_refill(challenge_data)
            mastery_handoff=self.mastery_balance_handoff()
            if mastery_handoff:
                self.emit('log','Verified SP mastery screen handed directly to SP read / farm setup; inventory and credit checks are deferred to the next unpaid purchase boundary.')
            if not farm_in_progress and not intermediate_refill and not mastery_handoff:
                self.refresh_inventory(stay_pause=True)
            if self.credit_limited:
                # Do not navigate away from an already launched/resumable farm.
                # Its credit gate ran before launch; recheck before the next buy.
                # A mastery-tree SP handoff also defers safely because no
                # purchase can occur until convert() runs its fresh gate.
                if (not farm_in_progress and
                        (floor_for(g.data) is not None or not intermediate_refill and not mastery_handoff)):
                    proof = self.credit_budget()
                    if not proof['affordable_purchases']:
                        self.finish_credit_limit(proof)
                        continue
            if g.data['phase'] == 'farm':
                trial=self.farm_trial
                trial.prepare(g.data,self.challenge)
                trial.started(f"{g.data['id']}_{g.data['farm_runs']}",self.challenge.profile.share_code)
                self.emit('stage', 'farm')
                self.challenge.target_sp=refill_target(g.data['limit']-g.data['rewards'],g.data['reserve_sp'])
                self.challenge.reserve_sp=g.data['reserve_sp']
                points = self.challenge.run(f"{g.data['id']}_{g.data['farm_runs']}", return_collection=False)
                challenge_data=getattr(self.challenge,'data',{})
                if isinstance(challenge_data,dict) and challenge_data.get('skipped_refill') is True:
                    if challenge_data.get('launch_attempts',0):
                        raise RuntimeError('A launched challenge cannot be counted as a skipped refill')
                    g.save(phase='inspect_sp',last_sp=points,
                           sp_observed_at=datetime.now().isoformat(timespec='seconds'),final_top_up=True)
                    continue
                trial.completed(self.challenge)
                g.save(phase='inspect_sp', farm_runs=g.data['farm_runs']+1, last_sp=points,
                       challenge_sp_rewards=g.data['rewards'],
                       sp_observed_at=datetime.now().isoformat(timespec='seconds'),
                       final_top_up=getattr(self.challenge,'data',{}).get('exit_reason')=='intentional_target_top_up')
                continue
            self.emit('stage', 'inspect_sp')
            points = self.completed_challenge_sp(challenge_data)
            if points is None:
                points = self.boundary('sp_read',self.nav.available_sp)
            else:
                self.emit('log',f'Reusing the challenge exit SP proof ({points}); duplicate menu read skipped.')
            g.save(last_sp=points, sp_observed_at=datetime.now().isoformat(timespec='seconds'))
            from .refill_policy import mini_cap_batch
            from .analytics import read
            cap_batch=(getattr(self.challenge.profile,'share_code',None)=='169055890' and
                       mini_cap_batch(points,g.data['limit']-g.data['rewards'],g.data['reserve_sp'],
                                      read(g.path.parent/'analytics.json').get('farms',[])))
            if cap_batch:
                self.emit('log','Mini V2 cap avoidance: converting the near-full verified balance before another run would waste at least 21 SP.')
            mega_convert=False
            if getattr(self.challenge.profile,'share_code',None)=='155439962':
                from .refill_control import decision_from_files, describe
                policy=decision_from_files(points,refill_target(g.data['limit']-g.data['rewards'],g.data['reserve_sp']),
                                g.path.parent,self.challenge.profile,
                                reserve=g.data['reserve_sp'],check=self.nav.check)
                mega_convert=policy.get('mode')=='convert'
                self.emit('log',describe(policy,self.challenge.profile.name))
            count = funded_cars(points, g.data['limit']-g.data['rewards'], g.data['reserve_sp'],
                                allow_partial=starting_balance_allowed(g.data) or bool(g.data.get('final_top_up')) or cap_batch or mega_convert)
            if not count:
                self.emit('log', f'Refill toward {refill_target(g.data["limit"]-g.data["rewards"],g.data["reserve_sp"])} SP: verified {points}. No new car batch yet.')
                g.save(phase='farm')
                continue
            car_interval = g.data.get('cleanup_every_cars', 0)
            if type(car_interval) is int and car_interval > 0:
                until_cleanup = car_interval - (g.data['rewards'] -
                    g.data.get('cleanup_rewards_baseline', 0))
                if until_cleanup <= 0:
                    g.save(phase='periodic_cleanup')
                    continue
                count = min(count, until_cleanup)
            self.boundary('farm_to_collection',self.nav.return_collection)
            self.emit('refill_ready',dict(after_sp=points,cars=count))
            g.save(final_top_up=False)
            g.save(reservation=dict(id=datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
                goal_id=g.data['id'], count=count, points=points, reserve=g.data['reserve_sp'],
                previous_session=self.cars.data.get('id')))
            self.emit('log', f'{points} SP verified. Converting {count} Mad Mike cars before the next refill.')
            self.resume_reservation()
        self.progress()
        self.emit('stage', 'complete')

    def resume_reservation(self):
        reserved = self.goal.data['reservation']
        saved = self.cars.data
        if reserved['goal_id'] != self.goal.data['id']:
            raise RuntimeError('Batch reservation belongs to another mission')
        if saved.get('funding', {}).get('id') != reserved['id']:
            if saved.get('id') != reserved.get('previous_session') or (saved and saved.get('phase') != 'complete'):
                raise RuntimeError('Car session changed during batch reservation')
            self.cars.start('Full pipeline', reserved['count'], funding=reserved)
        saved = self.cars.data
        if saved['phase'] != 'collection' or any(saved[k] for k in ('bought', 'rewards', 'completed')):
            raise RuntimeError('Unbound reserved batch has unexpected activity; no counters inferred')
        self.bind(cycles=reserved['count'])
