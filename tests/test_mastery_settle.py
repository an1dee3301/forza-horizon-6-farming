from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest
import forza_cycle as core
from fh6.mastery_settle import settle_fresh_tree, NAMES


def observation(stamp=0, state='unknown', screen='mad_mike_mastery'):
    nodes = {name:{'state':'unavailable'} for name in NAMES}
    nodes['Head-Turner']['state']='available'
    nodes['Show Me Your Moves']['state']=state
    return SimpleNamespace(screen=screen,result=dict(screen=screen,nodes=nodes),
                           captured_monotonic=stamp,frame=None)


def harness(sequence):
    now=[0.0]
    nav=Mock()
    nav.focus_generation=0
    values=iter(sequence)
    def observe():
        now[0]+=.1
        return next(values)
    nav.observe.side_effect=observe
    nav.pause.side_effect=lambda delay:now.__setitem__(0,now[0]+delay)
    return nav,now


def test_valid_tree_has_no_added_wait():
    obs=observation(state='unavailable')
    nav=Mock()
    assert settle_fresh_tree(nav,obs) is obs
    nav.observe.assert_not_called()


def test_unknown_settles_on_two_fresh_complete_proofs_without_inputs():
    final=observation(.3,'unavailable')
    nav,now=harness([observation(.1),observation(.2,'unavailable'),final])
    assert settle_fresh_tree(nav,observation(),clock=lambda:now[0]) is final
    assert now[0]<1.2
    nav.key.assert_not_called()
    nav.keyboard_select.assert_not_called()


@pytest.mark.parametrize('state,screen',[('owned','mad_mike_mastery'),('unknown','garage_grid')])
def test_owned_or_wrong_screen_fails_immediately(state,screen):
    nav=Mock()
    with pytest.raises(RuntimeError):
        settle_fresh_tree(nav,observation(state=state,screen=screen))
    nav.observe.assert_not_called()


@pytest.mark.parametrize('state,screen',[('owned','mad_mike_mastery'),('unknown','garage_grid')])
def test_owned_or_changed_screen_during_wait_fails_on_first_frame(state,screen):
    nav,now=harness([observation(.1,state,screen)])
    with pytest.raises(RuntimeError):
        settle_fresh_tree(nav,observation(),clock=lambda:now[0])
    nav.observe.assert_called_once()
    nav.key.assert_not_called()


def test_unknown_timeout_is_bounded_and_never_authorizes_claim():
    nav,now=harness(observation(i*.1) for i in range(1,30))
    with pytest.raises(RuntimeError,match='no points spent'):
        settle_fresh_tree(nav,observation(),clock=lambda:now[0])
    assert 1.2 <= now[0] <= 1.3  # At most the in-flight capture exceeds the deadline.
    assert nav.observe.call_count <= 10
    nav.key.assert_not_called()


def test_frame_finishing_after_deadline_is_rejected():
    nav,now=harness([observation(.1,'unavailable'),observation(.2,'unavailable')])
    nav.pause.side_effect=lambda delay:now.__setitem__(0,1.19)
    with pytest.raises(RuntimeError):
        settle_fresh_tree(nav,observation(),clock=lambda:now[0])
    nav.key.assert_not_called()


def test_reused_observation_is_not_fresh():
    nav,now=harness([observation(0,'unavailable')])
    with pytest.raises(RuntimeError):
        settle_fresh_tree(nav,observation(),clock=lambda:now[0])


def test_actual_failure_classifier_fixture_still_unknown_and_can_only_settle():
    path=Path(__file__).resolve().parents[1]/'failures/pipeline_20260926_145430_716950.png'
    if not path.exists():
        pytest.skip('Private local failure image not distributed')
    frame=cv2.imread(str(path))
    result=core.Recognizer().inspect(frame)
    assert result['screen']=='mad_mike_mastery'
    assert result['nodes']['Show Me Your Moves']==dict(state='unknown',pink=0.0,white=0.0,dark=.447)
    original=deepcopy(result)
    obs=SimpleNamespace(screen=result['screen'],result=result,frame=frame,captured_monotonic=0)
    final=observation(.2,'unavailable')
    nav,now=harness([observation(.1,'unavailable'),final])
    assert settle_fresh_tree(nav,obs,clock=lambda:now[0]) is final
    assert result==original
    nav.key.assert_not_called()
