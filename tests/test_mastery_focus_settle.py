from unittest.mock import Mock, patch
import pytest
from fh6 import mastery_focus_settle as focus

@pytest.mark.parametrize('ready,delay',[(True,.05),(False,.05),(True,.36)])
def test_poll_deadline_and_no_input(ready,delay):
    clock=[0.];check=Mock()
    def observe(**kwargs):
        clock[0]+=delay
        return object(),dict(screen='mad_mike_mastery',selection={'name':'target' if ready else 'old'},nodes={'target':{'state':'available'}})
    result,elapsed,captures=focus.settle(observe,check,lambda n:clock.__setitem__(0,clock[0]+n),'target',clock=lambda:clock[0])
    assert (result is not None)==(ready and delay<.35)
    assert captures>=1
    assert elapsed<=.42


@pytest.mark.parametrize('aged,flicker',[(False,False),(True,False),(False,True)])
def test_real_mastery_loop_keeps_three_fresh_selection_and_owned_proofs(aged,flicker):
    from test_mastery_focus_proofs import MasteryFreshnessTests
    state=MasteryFreshnessTests().run_cycle(aged=aged,owned_flicker=flicker)
    assert state['actions'].count('enter')==6
    assert state['actions'].count('right')==2
    assert state['actions'].count('up')==3


def test_unsettled_after_one_direction_never_repeats_or_enters():
    from test_mastery_focus_proofs import MasteryFreshnessTests
    with patch.object(focus,'settle',return_value=(None,.35,4)), \
         patch.object(focus,'target_ready',return_value=False):
        state=MasteryFreshnessTests().run_cycle(expect_error=True)
    assert state['actions']==['enter','right']
    assert 'no repeat direction or Enter' in state['error']


def test_timeout_fresh_fallback_keeps_proofs_without_second_delay():
    from test_mastery_focus_proofs import MasteryFreshnessTests
    with patch.object(focus,'settle',return_value=(None,.35,4)):
        state=MasteryFreshnessTests().run_cycle()
    assert state['actions'].count('enter')==6
    assert state['actions'].count('right')==2
    assert state['actions'].count('up')==3

def test_nonfast_mastery_retains_original_pacing():
    from test_mastery_focus_proofs import MasteryFreshnessTests
    with patch.object(focus,'settle',side_effect=AssertionError('nonfast must not poll')):
        state=MasteryFreshnessTests().run_cycle(fast=False)
    assert state['actions'].count('enter')==6
    assert state['actions'].count('right')==2
    assert state['actions'].count('up')==3
