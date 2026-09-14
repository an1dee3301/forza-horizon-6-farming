"""One persisted state machine for the complete route and purchase-only mode."""
import json

from . import purchase, mastery

STAGES = [
    ('collection', 'Home / festival → Collection Journal'),
    ('buy', 'Buy the Mad Mike Mazda'),
    ('bought', 'Confirm purchase → Car Collection'),
    ('paints', 'Open My Cars (saved-stage compatibility)'),
    ('choose', 'My Cars → Recently Added → All Cars'),
    ('open_mastery', 'Upgrades & Tuning → Car Mastery'),
    ('mastery', 'Claim and verify all six mastery nodes'),
    ('return', 'Return to Car Collection → repeat'),
]


def ledger_data(ledger):
    return json.loads(ledger.path.read_text(encoding='utf-8')) if ledger.path.exists() else {}


class Pipeline:
    def __init__(self, nav, ledger, session, emit=lambda *args: None):
        self.nav, self.ledger, self.session, self.emit = nav, ledger, session, emit

    def verify_fresh_tree(self, obs):
        """Use the Cars-tab SP proof pinned to this uninterrupted batch."""
        data = self.session.data
        funding = data.get('funding')
        if not funding:
            self.nav.verify_fresh_mastery(obs)
            return
        points, count, completed = (funding.get('points'), funding.get('count'),
                                    data.get('completed'))
        if (type(points) is not int or type(count) is not int or
                type(completed) is not int or count < completed + 1 or
                points - completed * 21 < 21):
            raise RuntimeError('Saved Cars-tab SP funding does not cover this mastery claim')
        # The starting balance was read twice from the Cars tab. Every prior
        # car in this batch has six independently verified owned nodes, so the
        # remaining reservation is an exact lower bound for this next claim.
        self.nav.verify_fresh_mastery(obs,
            verified_points=points - completed * 21)

    def resume_choice_from_tree(self, obs):
        # This checkpoint precedes every mastery input. Known owned nodes mean
        # we are still looking at another car, often the previous completed copy.
        # Re-select the untouched newest purchase; never buy again here.
        nodes = obs.result.get('nodes', {})
        states = [node.get('state') for node in nodes.values()]
        if len(states) == 6 and all(s in {'owned', 'locked', 'available'} for s in states) and 'owned' in states:
            self.emit('log', 'Selection resumed on a used Mazda. Returning to the untouched Recently Added car.')
            self.nav.back_home()
            self.nav.choose_car()
            self.session.save(phase='open_mastery')
            return
        self.verify_fresh_tree(obs)
        self.session.save(phase='mastery')

    def run(self, max_cycles=None):
        nav, session = self.nav, self.session
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 1):
            raise ValueError('The cycle boundary must be a positive whole number')
        starting_completed = session.data['completed']
        record = ledger_data(self.ledger)
        if record.get('status') == 'pending' and session.data['phase'] == 'buy' and \
                record.get('id') != session.data.get('purchase_before'):
            # Read-only recovery: only a still-visible success receipt can
            # confirm this pending attempt. Never send another purchase key.
            receipt = nav.wait('purchase_success')
            self.ledger.confirm(receipt.frame)
            self.emit('log', 'Verified the pending purchase from its visible success receipt.')
        self.ledger.ready()
        if session.data['phase'] == 'collection':
            # The pause-preserving inventory refresh deliberately leaves the
            # game on Pause before a funded conversion batch.  A restarted
            # pipeline used to wait forever because Navigator.collection()
            # only accepts Home/journal screens.  Recover this reversible
            # pre-purchase state once, before entering the cycle; no purchase
            # or ledger state has changed yet.
            observe = getattr(nav, 'observe', None)
            if callable(observe):
                current = observe()
                if current.screen == 'pause_menu':
                    self.emit('log', 'Collection checkpoint is in the pause menu; restoring Home and Collection before buying.')
                    nav.return_collection()
        if session.data['phase']=='buy' and record.get('id')==session.data.get('purchase_before'):
            # A manual menu change can leave an unpurchased checkpoint at Home.
            # The transaction recognizer cannot navigate Home and would retry
            # its collection wait forever. Recover only known reversible menus,
            # before a new ledger attempt; orphan offers keep their old cancel
            # path and uncertain/confirmed new attempts never come through here.
            observe=getattr(nav,'observe',None)
            if callable(observe):
                current=observe()
                if current.screen in {'cars','campaign','home_tab','journal','discover','upgrades','showroom'}:
                    self.emit('log','Unpurchased checkpoint is outside Collection; restoring the verified journal route before buying.')
                    nav.collection()
                elif current.screen == 'pause_menu':
                    self.emit('log','Unpurchased checkpoint is in the pause menu; restoring Home and Collection before buying.')
                    nav.return_collection()
        if session.data['phase'] == 'mastery':
            # Only a resumed partial tree needs this recovery. Ordinary cycles
            # already verified their tree in open_mastery, with no extra trip.
            nav.resume_mastery()
        while session.data['phase'] != 'complete':
            nav.check()
            data = session.data
            phase = data['phase']
            self.emit('cycle_stage', dict(batch_id=data['id'], cycle=data['completed']+1,
                phase=phase, goal_id=(data.get('funding') or {}).get('goal_id')))
            self.emit('stage', phase)
            self.emit('progress', dict(data))
            if phase == 'collection':
                nav.collection()
                session.save(phase='buy', purchase_before=ledger_data(self.ledger).get('id'))
            elif phase == 'buy':
                record = ledger_data(self.ledger)
                new_record = record.get('id') and record['id'] != data.get('purchase_before')
                if new_record and record.get('status') in {'confirmed', 'resolved_bought'}:
                    # Includes a stop/crash after confirmation but before checkpointing.
                    self.emit('log', 'Recovered the already-confirmed purchase; no new purchase sent.')
                else:
                    purchase.buy(nav, self.ledger)
                session.save(phase='bought', bought=data['bought']+1)
            elif phase == 'bought':
                purchase.acknowledge(nav)
                session.save(phase='return' if data['mode'] == 'Buy only' else 'choose')
            elif phase == 'paints':
                # Old saved runs may still use this phase; new runs skip it.
                session.save(phase='choose')
            elif phase == 'choose':
                obs = nav.wait({'paints', 'car_select', 'garage_grid', 'garage_filter', 'sort_selection', 'cars',
                                'campaign', 'home_tab', 'collection_grid', 'upgrades', 'mad_mike_mastery', 'recent_jump', 'showroom'})
                if obs.screen == 'showroom':
                    nav.back_home()
                    obs = nav.wait({'cars', 'campaign', 'home_tab'})
                if obs.screen == 'mad_mike_mastery':
                    self.resume_choice_from_tree(obs)
                elif obs.screen in {'cars', 'campaign', 'home_tab', 'upgrades'} and obs.doc.has('123 Mad Mike 808', (100, 35, 650, 50), contains=True):
                    obs = nav.open_mastery()
                    self.resume_choice_from_tree(obs)
                else:
                    nav.choose_car()
                    session.save(phase='open_mastery')
            elif phase == 'open_mastery':
                obs = nav.wait({'paints', 'cars', 'campaign', 'home_tab', 'showroom', 'upgrades', 'mad_mike_mastery'})
                if obs.screen != 'mad_mike_mastery':
                    obs = nav.open_mastery()
                self.verify_fresh_tree(obs)
                session.save(phase='mastery')
            elif phase == 'mastery':
                # Restarting never skips the screen/model checks in the mastery module.
                mastery.claim(nav)
                session.save(phase='return', rewards=data['rewards']+1)
            elif phase == 'return':
                obs = nav.wait({'mad_mike_mastery', 'upgrades', 'cars', 'home_tab',
                                'campaign', 'collection_grid', 'journal', 'discover', 'manufacturers'})
                if obs.screen == 'manufacturers':
                    nav.key('esc')
                    obs = nav.wait('collection_grid', previous='manufacturers')
                if obs.screen not in {'collection_grid', 'campaign', 'journal', 'discover'}:
                    nav.back_home()
                nav.collection()
                completed = data['completed']+1
                done = data['limit'] > 0 and completed >= data['limit']
                session.finish_cycle(completed, done)
                self.emit('cycle_complete', dict(batch_id=data['id'], cycle=completed,
                    goal_id=(data.get('funding') or {}).get('goal_id'),
                    elapsed_seconds=session.data.get('cycle_seconds', [None])[-1],
                    bought=data['bought'], rewards=data['rewards'], sp=data.get('observed_sp')))
                self.emit('log', f'Cycle {completed} finished. Car Collection is ready.')
                if max_cycles is not None and completed - starting_completed >= max_cycles:
                    break
            else:
                raise RuntimeError(f'Unknown saved stage: {phase}')
        self.emit('progress', dict(session.data))
        self.emit('stage', 'complete' if session.data['phase'] == 'complete' else 'collection')
