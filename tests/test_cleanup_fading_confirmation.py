from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from fh6.navigation import Navigator, fading_removal_title
from fh6.ocr import Document, Text
from fh6.garage_cleanup import GarageCleanup, wait_after_removal_yes


def observe(doc,pending):
    nav=Navigator.__new__(Navigator)
    nav.running=Event()
    nav.running.set()
    nav.capture=SimpleNamespace(grab=lambda monitor:np.zeros((1080,1920,4),dtype=np.uint8))
    nav.monitor={}
    nav.recognizer=SimpleNamespace(inspect=lambda frame:{'screen':'unknown'})
    nav.reader=SimpleNamespace(read=lambda frame:doc)
    nav.measured=lambda name,callback:callback()
    nav.probe=Mock()
    nav.focus_generation=0
    nav._garage_remove_pending=pending
    return nav.observe_sync()


@pytest.mark.parametrize('text,box',[
    ('Remove Car From Garce',(675,414,572,35)),
    ('Remove Car From Garace',(675,414,571,44)),
    ('Remove Car From',(672,413,400,35))])
def test_observed_text_boxes_only_allow_pending_read_only_transition(text,box):
    doc=Document([Text(text,box)])
    assert fading_removal_title(doc)
    assert observe(doc,True).screen=='unknown'
    with pytest.raises(RuntimeError,match='Unexpected dialog'):
        observe(doc,False)


@pytest.mark.parametrize('text',['Insufficient credits','Delete car','Unsaved changes','Garage is full'])
def test_other_errors_still_reject(text):
    doc=Document([Text('Remove Car From',(672,413,400,35)),Text(text,(600,500,400,30))])
    with pytest.raises(RuntimeError,match='Unexpected dialog'):
        observe(doc,True)


@pytest.mark.parametrize('box',[(672,700,400,35),(50,50,572,35),(675,414,200,35)])
def test_non_native_or_short_fragments_reject(box):
    doc=Document([Text('Remove Car From',box)])
    assert not fading_removal_title(doc)
    with pytest.raises(RuntimeError,match='Unexpected dialog'):
        observe(doc,True)


@pytest.mark.parametrize('fails',[False,True])
def test_pending_scope_is_restored_and_no_input_repeated(fails):
    nav=Mock()
    nav._garage_remove_pending=False
    def wait(*args,**kwargs):
        assert nav._garage_remove_pending is True
        assert kwargs['stable_frames']==2
        if fails:
            raise RuntimeError('Timed out waiting for garage_grid')
        return 'grid'
    nav.wait.side_effect=wait
    if fails:
        with pytest.raises(RuntimeError,match='Timed out'):
            wait_after_removal_yes(nav)
    else:
        assert wait_after_removal_yes(nav)=='grid'
    assert nav._garage_remove_pending is False
    nav.key.assert_not_called()
    nav.keyboard_select.assert_not_called()
    nav.wait.assert_called_once()


def test_cleanup_wait_failure_does_not_repeat_yes_or_record_removal():
    grid=SimpleNamespace(screen='garage_grid',frame=None,
        doc=Document([Text('#123 MAD MIKE 808',(450,220,260,30))]))
    nav=Mock()
    nav.fast_navigation=False
    nav.wait.side_effect=[grid,grid,RuntimeError('Timed out waiting for garage_grid')]
    tracker=Mock()
    tracker.data={'garage_cleanup':{}}
    with patch('fh6.garage_cleanup.selected_mad_mike'),patch('fh6.garage_cleanup.update_panel'), \
            patch('fh6.garage_cleanup.visual_gate',return_value=True):
        with pytest.raises(RuntimeError,match='Timed out'):
            GarageCleanup(nav,tracker).run()
    assert [c.args for c in nav.key.call_args_list]==[
        ('enter',),*[('down',)]*4,('enter',),('down',),('enter',)]
    assert not any(c.args[0]=='garage_removed' for c in tracker.event.call_args_list)
