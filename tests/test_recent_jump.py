"""Synthetic, isolated route tests; no runtime files, OCR engine, or game input."""
from types import SimpleNamespace
import pytest
from fh6 import navigation as nav
from fh6 import recent_jump as route
from fh6.ocr import Document, Text


def obs(monkeypatch, first=False):
    monkeypatch.setattr(nav,'selected_card',lambda frame:(400,204 if first else 456,340,260))
    return SimpleNamespace(frame=object(),screen='garage_grid',result={},captured_monotonic=10.,
        doc=Document([Text('All Cars',(440,160,100,30)),Text('Jump to Recently Added',(900,990,260,25)),
                      Text('MAD MIKE 808',(415,222,200,23)),Text('1974 MAZDA',(415,249,180,18)),
                      Text('NEW',(685,394,35,14))]))


def test_both_positions(monkeypatch):
    before=obs(monkeypatch)
    assert route.one_up_eligible(before,now=10.1)
    assert not route.already_first_new(before,now=10.1)
    after=obs(monkeypatch,True)
    assert route.already_first_new(after,now=10.1)


@pytest.mark.parametrize('bad',['stale','future','screen','sort','new','neighbor','all','position'])
def test_reject_bad_proof(monkeypatch,bad):
    frame=obs(monkeypatch)
    if bad=='stale':frame.captured_monotonic=8
    if bad=='future':frame.captured_monotonic=11
    if bad=='screen':frame.screen='car_select'
    if bad=='sort':frame.doc.lines[1]=Text('Jump to Manufacturer',(900,990,260,25))
    if bad=='new':frame.doc.lines.pop()
    if bad=='neighbor':frame.doc.lines[-1]=Text('NEW',(720,394,40,14))
    if bad=='all':frame.doc.lines.pop(0)
    if bad=='position':monkeypatch.setattr(nav,'selected_card',lambda f:(732,456,340,260))
    assert not route.one_up_eligible(frame,now=10.1)


@pytest.mark.parametrize('outcome',['success','dropped','unknown','focus','stale'])
def test_one_pulse_and_fresh_destination(monkeypatch,outcome):
    before=obs(monkeypatch)
    monkeypatch.setattr(route.time,'monotonic',lambda:10.1)
    keys=[]
    fake=SimpleNamespace(focus_generation=1,check=lambda:None,key=keys.append,last=before)
    def wait(*args,**kwargs):
        after=obs(monkeypatch,True);after.captured_monotonic=10.05
        if outcome=='success':
            assert kwargs['predicate'](after)
            return after
        if outcome=='stale':
            assert not kwargs['predicate'](before)
        if outcome=='focus':
            fake.focus_generation=2
            kwargs['predicate'](after)
        if outcome=='unknown':fake.last=SimpleNamespace(screen='unknown')
        raise RuntimeError('Timed out waiting for garage_grid')
    fake.wait=wait
    if outcome in {'unknown','focus'}:
        with pytest.raises(RuntimeError):route.try_one_up(fake,before)
    else:assert (route.try_one_up(fake,before) is not None)==(outcome=='success')
    assert keys==['up']


@pytest.mark.parametrize('success',[True,False])
def test_choose_dispatch(monkeypatch,success):
    frame=obs(monkeypatch)
    fake=nav.Navigator.__new__(nav.Navigator)
    fake.fast_navigation=True;fake.garage_recent_sort_verified=True
    keys=[]
    fake.wait=lambda *a,**k:frame
    fake.key=keys.append;fake.pause=lambda n:None;fake.emit=lambda *a:None
    fake.enter_fresh_car=lambda f:keys.append('normal_verified_entry')
    monkeypatch.setattr(nav,'set_favorites',lambda *a:frame)
    monkeypatch.setattr(route,'try_one_up',lambda *a:frame if success else None)
    fake.choose_car()
    assert keys==(['normal_verified_entry'] if success else ['backspace','normal_verified_entry'])
