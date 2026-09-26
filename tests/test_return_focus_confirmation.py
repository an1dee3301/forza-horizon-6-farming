from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest

@pytest.mark.parametrize('proved',[True,False])
def test_keyboard_confirm_preserves_single_enter_and_no_second_pause(monkeypatch,proved):
    from fh6 import navigation
    target=NS(center=(20,20),box=(10,10,20,20))
    obs=NS(screen='journal',frame=object(),doc=NS(find=lambda *a:[target],unique=lambda *a:target))
    nav=navigation.Navigator.__new__(navigation.Navigator)
    nav.fast_navigation=True
    nav.wait=Mock(return_value=obs)
    nav.pause=Mock();nav.key=Mock();nav.emit=Mock()
    monkeypatch.setattr(navigation,'focus_boxes',lambda f:[(0,0,50,50)])
    probe=Mock(return_value=NS(proved=proved,observation=obs if proved else None,elapsed=.2,captures=2))
    monkeypatch.setattr(navigation,'wait_target_focus',probe)
    nav.keyboard_select('journal','Master Explorer')
    nav.key.assert_called_once_with('enter')
    nav.pause.assert_not_called()
    assert nav.wait.call_count == (1 if proved else 2)
    assert probe.call_args.kwargs['timeout'] == .3

@pytest.mark.parametrize('fast,screen,label',[(False,'journal','Master Explorer'),(False,'discover','Car Collection'),(True,'manufacturers','Mazda')])
def test_other_confirmations_keep_original_pause(monkeypatch,fast,screen,label):
    from fh6 import navigation
    target=NS(center=(20,20),box=(10,10,20,20))
    obs=NS(screen=screen,frame=object(),doc=NS(find=lambda *a:[target],unique=lambda *a:target))
    nav=navigation.Navigator.__new__(navigation.Navigator)
    nav.fast_navigation=fast
    nav.check=Mock();nav.monitor={'left':0,'top':0}
    import sys
    monkeypatch.setitem(sys.modules,'pyautogui',NS(moveTo=Mock()))
    nav.wait=Mock(return_value=obs)
    nav.pause=Mock();nav.key=Mock();nav.emit=Mock()
    monkeypatch.setattr(navigation,'focus_boxes',lambda f:[(0,0,50,50)])
    monkeypatch.setattr(navigation,'wait_target_focus',Mock(side_effect=AssertionError('unsupported polling')))
    nav.keyboard_select(screen,label)
    nav.key.assert_called_once_with('enter')
    nav.pause.assert_not_called()

@pytest.mark.parametrize('fault',[None,'focus','screen','same_frame','wrong_target'])
def test_return_helper_requires_distinct_fresh_target_proof_without_input(fault):
    from fh6.return_focus_settle import wait_target_focus
    clock=[0.0];frame=object();count=[0]
    target=NS(center=(20,20),box=(10,10,20,20))
    nav=NS(focus_generation=0,check=Mock(),key=Mock())
    nav.pause=lambda delay:clock.__setitem__(0,clock[0]+delay)
    def observe():
        count[0]+=1;clock[0]+=.06
        if fault=='focus':nav.focus_generation+=1
        return NS(screen='cars' if fault=='screen' else 'journal',frame=frame if fault=='same_frame' else object(),doc=NS(find=lambda *a:[] if fault=='wrong_target' else [target]))
    nav.observe=observe
    if fault in ('focus','screen'):
        with pytest.raises(RuntimeError):wait_target_focus(nav,'journal','Master Explorer',lambda f:[(0,0,50,50)],clock=lambda:clock[0])
    else:
        result=wait_target_focus(nav,'journal','Master Explorer',lambda f:[(0,0,50,50)],clock=lambda:clock[0])
        assert result.proved == (fault is None)
        if result.proved:assert result.captures==2
    nav.key.assert_not_called()
