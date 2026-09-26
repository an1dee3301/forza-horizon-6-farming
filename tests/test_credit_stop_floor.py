import pytest
from unittest.mock import Mock
from fh6.credit_stop_floor import apply, floor_for
from fh6.credit_limit import PRICE, SOURCE, CreditProofUnavailable


import tempfile
import unittest
from pathlib import Path
from forza_cycle import PurchaseLedger
from fh6.production import GoalSession, Production
from fh6.session import Session

class CreditProductionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.goal = GoalSession(folder/'goal.json')
        self.goal.start_goal(1)
        self.goal.save(credit_limited=True, credit_account='ExampleDriver',
                       account_baseline=dict(goal_id=self.goal.data['id'], fields=dict(sp=999)))
        self.cars = Session(folder/'session.json')
        self.ledger = PurchaseLedger(folder/'purchases')
        self.balance, self.credits, self.purchases, self.claims, self.farms = 999, 2*PRICE, 0, 0, 0
        self.nav = Mock()
        self.nav.available_sp.side_effect = lambda:self.balance
        self.challenge = Mock()
        self.challenge.data = {}
        def farm(*args, **kwargs):
            self.farms += 1
            self.balance = 999
            return self.balance
        self.challenge.run.side_effect = farm
        self.budgeter = Mock()
        self.budget_reads = 0
        def budget(*args, **kwargs):
            self.budget_reads += 1
            return dict(observed_credits=self.credits, purchases_after_observation=0,
                affordable_purchases=self.credits//PRICE, source=SOURCE,
                credits_event=f'fresh-credit-event-{self.budget_reads}')
        self.budgeter.budget.side_effect = budget
        owner = self
        class Pipeline:
            def __init__(self, nav, ledger, session, emit):
                self.session, self.emit = session, emit
            def run(self, max_cycles):
                s = self.session
                for _ in range(max_cycles):
                    if s.data['phase'] in {'collection', 'buy'}:
                        owner.assertGreaterEqual(owner.credits, PRICE)
                        owner.purchases += 1
                        owner.credits -= PRICE
                        s.save(bought=s.data['bought']+1, phase='mastery')
                    if s.data['phase'] != 'return':
                        owner.assertGreaterEqual(owner.balance, 21)
                        owner.balance -= 21
                        owner.claims += 1
                        s.save(rewards=s.data['rewards']+1, phase='return')
                        self.emit('progress', s.data)
                    s.finish_cycle(s.data['completed']+1, s.data['completed']+1 >= s.data['limit'])
                    self.emit('progress', s.data)
        self.cleaned = 0
        def terminal_cleaner(nav, emit):
            self.cleaned += 1
            return self.goal.data.get('bought', 0)
        self.job = Production(self.nav, self.ledger, self.goal, self.cars, self.challenge,
                              pipeline_factory=Pipeline, credit_budgeter=self.budgeter,
                              terminal_cleaner=terminal_cleaner)


FLOOR=1_000_000
@pytest.fixture
def owner():
    case=CreditProductionFixture();case.setUp()
    case.goal.save(credit_stop_floor={'goal_id':case.goal.data['id'],'credits':FLOOR})
    def budget(*args,**kwargs):
        case.budget_reads+=1
        return dict(goal_id=case.goal.data['id'],gamertag=case.goal.data['credit_account'],available_credits=case.credits,observed_credits=case.credits,purchases_after_observation=0,affordable_purchases=case.credits//PRICE,source=SOURCE,credits_event=f'fresh-{case.budget_reads}')
    case.budgeter.budget.side_effect=budget
    yield case
    case.doCleanups()

@pytest.mark.parametrize('available,count',[(FLOOR-1,0),(FLOOR,0),(FLOOR+PRICE-1,0),(FLOOR+PRICE,1),(FLOOR+2*PRICE+20,2)])
def test_capacity_never_crosses_floor(owner,available,count):
    owner.credits=available
    proof=owner.job.credit_budget()
    assert proof['affordable_purchases']==count
    assert available-count*PRICE>=min(available,FLOOR)

def test_paid_copy_finishes_and_no_farm_topup_reopen(owner):
    owner.credits=FLOOR+12
    owner.cars.start('Full pipeline',47);owner.job.bind(cycles=47)
    owner.cars.save(bought=1,phase='mastery')
    owner.job.run()
    assert (owner.claims,owner.purchases,owner.farms)==(1,0,0)
    assert owner.cleaned==1 and owner.goal.data['phase']=='complete'
    assert owner.goal.data['end_reason']=='credit_stop_floor'
    assert 'terminal_sp_completed_at' not in owner.goal.data
    owner.credits+=1_000_000;owner.job.run()
    assert (owner.cleaned,owner.purchases,owner.farms)==(1,0,0)

def test_partial_batch_caps_purchases_then_cleans(owner):
    owner.credits=FLOOR+2*PRICE+7
    owner.cars.start('Full pipeline',47);owner.job.bind(cycles=47)
    owner.job.run()
    assert (owner.purchases,owner.claims,owner.farms,owner.cleaned)==(2,2,0,1)
    assert owner.credits==FLOOR+7
    assert any(c.kwargs=={'force':True,'full_header':True} for c in owner.budgeter.budget.call_args_list)

def test_cleanup_resume_never_buys_or_farms(owner):
    owner.credits=FLOOR
    owner.job.terminal_cleaner=Mock(side_effect=RuntimeError('interrupted'))
    with pytest.raises(RuntimeError,match='interrupted'):owner.job.run()
    assert owner.goal.data['phase']=='garage_cleanup'
    owner.job.terminal_cleaner=Mock(return_value=3);owner.job.run()
    assert owner.goal.data['phase']=='complete'
    assert (owner.purchases,owner.farms)==(0,0)

def test_fresh_unavailable_preserves_cap_not_completion(owner):
    owner.credits=FLOOR
    proof=owner.job.credit_budget()
    owner.budgeter.budget.side_effect=CreditProofUnavailable('unreadable')
    with pytest.raises(CreditProofUnavailable):owner.job.finish_credit_limit(proof)
    assert owner.goal.data['phase']!='complete'
    assert owner.goal.data['credit_budget']['affordable_purchases']==0
    assert owner.purchases==0

def test_fresh_balance_can_cancel_early_stop(owner):
    owner.credits=FLOOR
    proof=owner.job.credit_budget()
    owner.credits+=PRICE
    owner.job.finish_credit_limit(proof)
    assert owner.goal.data.get('end_reason')!='credit_stop_floor'
    assert owner.goal.data['credit_budget']['affordable_purchases']==1

def test_default_and_wrong_goal():
    assert floor_for({'id':'g'}) is None
    proof={'available_credits':123}
    assert apply({'id':'g'},proof) is proof
    with pytest.raises(RuntimeError):floor_for({'id':'g','credit_stop_floor':{'goal_id':'other','credits':FLOOR}})

def test_configuration_is_explicit_and_persistent(owner):
    from fh6.credit_stop_floor import configure
    previous=dict(owner.goal.data['credit_stop_floor'])
    configure(owner.goal)
    assert owner.goal.data['credit_stop_floor']==previous
    configure(owner.goal,FLOOR)
    assert owner.goal.data['credit_limited'] is True
    with pytest.raises(ValueError,match='saved credit floor'):configure(owner.goal,FLOOR+1)
    owner.goal.save(phase='complete',end_reason='credit_stop_floor')
    with pytest.raises(ValueError,match='completed goal'):configure(owner.goal,FLOOR)

@pytest.mark.parametrize('value',[0,-1,True,1.5,1_000_000_000])
def test_invalid_configuration_rejected(owner,value):
    from fh6.credit_stop_floor import configure
    with pytest.raises(ValueError):configure(owner.goal,value)


def test_new_floor_binds_identified_account(owner):
    from fh6.credit_stop_floor import configure
    owner.goal.data.pop('credit_stop_floor');owner.goal.data.pop('credit_account')
    with pytest.raises(ValueError,match='identified'):configure(owner.goal,FLOOR)
    configure(owner.goal,FLOOR,account='ExampleDriver')
    assert owner.goal.data['credit_stop_floor']=={'goal_id':owner.goal.data['id'],'credits':FLOOR}
    assert owner.goal.data['credit_account']=='ExampleDriver'


def test_bridge_optional_floor():
    from test_wheelspin_bridge import bridge,args
    values=args(mode=bridge.GOAL_MODE,target='10')
    assert bridge.configuration(values,{},{}).get('credit_floor') is None
    values.credit_floor=FLOOR
    assert bridge.configuration(values,{}, {})['credit_floor']==FLOOR
    values.mode='Wheelspin Lab'
    with pytest.raises(ValueError,match='Credit floor'):bridge.configuration(values,{}, {})

def test_final_only_survives_resume_and_skips_batch_cleanup(owner):
    from fh6.credit_stop_floor import configure_cleanup
    configure_cleanup(owner.goal,'final_only')
    owner.goal.save(cleanup_after_each_batch=True,cleanup_every_batches=1,cleanup_every_cars=1)
    owner.goal.start_goal(owner.goal.data['limit'])
    assert owner.goal.data['cleanup_policy']=='final_only'
    assert owner.goal.data['cleanup_after_each_batch'] is False
    assert owner.goal.data['cleanup_every_batches']==owner.goal.data['cleanup_every_cars']==0
    owner.credits=FLOOR+100*PRICE
    owner.cars.start('Full pipeline',3);owner.job.bind(cycles=3)
    owner.job.convert()
    assert owner.goal.data['phase']=='inspect_sp'
    assert owner.cleaned==0 and owner.claims==3


def test_final_only_still_cleans_once_at_floor(owner):
    from fh6.credit_stop_floor import configure_cleanup
    configure_cleanup(owner.goal,'final_only')
    configure_cleanup(owner.goal)
    owner.credits=FLOOR+PRICE
    owner.cars.start('Full pipeline',47);owner.job.bind(cycles=47)
    owner.job.run()
    assert (owner.purchases,owner.cleaned,owner.farms)==(1,1,0)
    assert owner.goal.data['phase']=='complete'


def test_final_only_requires_floor_and_explicit_valid_policy(owner):
    from fh6.credit_stop_floor import configure_cleanup
    with pytest.raises(ValueError):configure_cleanup(owner.goal,'bad')
    owner.goal.data.pop('credit_stop_floor')
    with pytest.raises(ValueError,match='credit floor'):configure_cleanup(owner.goal,'final_only')


def test_bridge_final_only_optional():
    from test_wheelspin_bridge import bridge,args
    value=args(mode=bridge.GOAL_MODE,target='10',credit_floor=FLOOR,cleanup_policy='final_only')
    assert bridge.configuration(value,{}, {})['cleanup_policy']=='final_only'
    value.mode='Wheelspin Lab'
    with pytest.raises(ValueError):bridge.configuration(value,{}, {})
