from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from fh6.cleanup_spacing import spaced_four_to_focus
from fh6.garage_cleanup import GarageCleanup
from fh6.navigation import SelectedCardError
from fh6.ocr import Document, Text


def test_spacing_and_two_fresh_proofs_without_enter():
    nav=Mock()
    nav.focus_generation=0
    prove=Mock(return_value=True)
    assert spaced_four_to_focus(nav,prove) is nav.wait.return_value
    assert [c.args for c in nav.key.call_args_list]==[('down',)]*4
    assert [c.args for c in nav.pause.call_args_list]==[(.08,)]*4+[(.16,)]
    nav.wait.assert_called_once_with('car_action',timeout=1.2,stable_frames=2,predicate=prove)


def test_timeout_never_repeats_group_or_confirms():
    nav=Mock()
    nav.focus_generation=0
    nav.wait.side_effect=RuntimeError('Timed out waiting for car_action')
    assert spaced_four_to_focus(nav,lambda obs:False) is None
    assert [c.args for c in nav.key.call_args_list]==[('down',)]*4
    nav.keyboard_select.assert_not_called()


def test_focus_change_stops_before_next_input():
    nav=Mock()
    nav.focus_generation=0
    nav.pause.side_effect=lambda delay:setattr(nav,'focus_generation',1)
    with pytest.raises(RuntimeError,match='focus changed'):
        spaced_four_to_focus(nav,lambda obs:True)
    nav.key.assert_called_once_with('down')
    nav.wait.assert_not_called()


@pytest.mark.parametrize('visual_start,proof',[(True,True),(True,False),(False,True),(False,False)])
def test_cleanup_preserves_identity_target_confirmation_and_journal(visual_start,proof):
    grid=SimpleNamespace(screen='garage_grid',frame=None,
        doc=Document([Text('#123 MAD MIKE 808',(450,220,260,30))]))
    action=SimpleNamespace(screen='car_action',frame=None,doc=Document([
        Text('Get In Car',(800,450,200,30)),Text('Remove Car From Garage',(800,650,300,30))]))
    empty=SimpleNamespace(screen='garage_grid',frame=None,doc=Document([]))
    nav=Mock()
    nav.fast_navigation=True
    nav.wait.side_effect=[grid,grid]+([] if visual_start and proof else [action])+[empty]
    tracker=Mock()
    tracker.data={'garage_cleanup':{'duplicates_disabled':True,'removed':0}}
    with patch('fh6.garage_cleanup.selected_mad_mike') as identity, \
            patch('fh6.garage_cleanup.selected_card',side_effect=SelectedCardError(0)), \
            patch('fh6.garage_cleanup.update_panel'), \
            patch('fh6.garage_cleanup.focused',return_value=True), \
            patch('fh6.garage_cleanup.spaced_four_to_focus',return_value=action if proof else None) as spaced, \
            patch('fh6.garage_cleanup.pulse_to_focus') as tight, \
            patch('fh6.garage_cleanup.visual_gate',side_effect=[visual_start,True,True]):
        assert GarageCleanup(nav,tracker).run()==1
    identity.assert_called_once_with(nav,grid)
    spaced.assert_called_once()
    tight.assert_not_called()
    assert ('garage_removed',{'count':1}) in [c.args for c in tracker.event.call_args_list]
    if proof:
        nav.keyboard_select.assert_not_called()
        assert [c.args for c in nav.key.call_args_list]==[('enter',),('enter',),('down',),('enter',)]
    else:
        nav.keyboard_select.assert_called_once_with('car_action','Remove Car From Garage')
        assert [c.args for c in nav.key.call_args_list]==[('enter',),('down',),('enter',)]


def test_unproven_start_cannot_send_spaced_group():
    grid=SimpleNamespace(screen='garage_grid',frame=None,
        doc=Document([Text('#123 MAD MIKE 808',(450,220,260,30))]))
    action=SimpleNamespace(screen='car_action',frame=None,doc=Document([
        Text('Get In Car',(800,450,200,30)),Text('Remove Car From Garage',(800,650,300,30))]))
    nav=Mock()
    nav.fast_navigation=True
    nav.wait.side_effect=[grid,grid,action]
    nav.keyboard_select.side_effect=RuntimeError('ambiguous focus')
    tracker=Mock()
    tracker.data={'garage_cleanup':{}}
    with patch('fh6.garage_cleanup.selected_mad_mike'),patch('fh6.garage_cleanup.update_panel'), \
            patch('fh6.garage_cleanup.focused',return_value=False), \
            patch('fh6.garage_cleanup.spaced_four_to_focus') as spaced, \
            patch('fh6.garage_cleanup.visual_gate',return_value=False):
        with pytest.raises(RuntimeError,match='ambiguous focus'):
            GarageCleanup(nav,tracker).run()
    spaced.assert_not_called()
    nav.key.assert_called_once_with('enter')
