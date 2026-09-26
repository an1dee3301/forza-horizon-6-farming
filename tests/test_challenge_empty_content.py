import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from fh6.ocr import Document,Text
from fh6.challenge_empty_content import empty_content_modal, dismiss_empty_content


def modal(stamp=1):
    lines=json.loads((Path(__file__).parent/'fixtures/challenge_empty_content.json').read_text())
    return NS(screen='unknown',doc=Document([Text(x['text'],tuple(x['box'])) for x in lines]),frame=object(),captured_monotonic=stamp)

def test_actual_failure_ocr_and_single_ack():
    a=modal();b=modal(2);gone=NS(screen='challenge_browser',doc=Document([]))
    nav=Mock();nav.observe.return_value=b
    nav.until.side_effect=lambda pred,*args,**kw: gone if pred(gone) else (_ for _ in ()).throw(AssertionError())
    assert empty_content_modal(a)
    assert dismiss_empty_content(nav,a) is gone
    nav.key.assert_called_once_with('enter');nav.check.assert_called_once()

@pytest.mark.parametrize('change',['title','body','footer','paid','duplicate','changed','stale'])
def test_reject_other_or_unstable_dialogs(change):
    a=modal();b=modal(2)
    if change=='paid':a.screen='purchase_confirm'
    elif change=='changed':b.doc=Document([])
    elif change=='stale':b.captured_monotonic=1
    elif change=='duplicate':a.doc.lines.append(a.doc.lines[-1])
    else:
        region={'title':(600,450,700,75),'body':(600,525,700,110),'footer':(60,965,200,100)}[change]
        x,y,w,h=region;a.doc.lines=[t for t in a.doc.lines if not(x<=t.center[0]<x+w and y<=t.center[1]<y+h)]
    nav=Mock();nav.observe.return_value=b
    if change in ('changed','stale'):
        with pytest.raises(RuntimeError):dismiss_empty_content(nav,a)
    else:assert dismiss_empty_content(nav,a) is a
    nav.key.assert_not_called()

def test_failed_dismissal_never_repeats_enter():
    nav=Mock();nav.observe.return_value=modal(2);nav.until.side_effect=RuntimeError('not dismissed')
    with pytest.raises(RuntimeError):dismiss_empty_content(nav,modal())
    nav.key.assert_called_once_with('enter')


def test_search_entry_acknowledges_before_existing_browser_search(monkeypatch):
    from fh6.farming import FarmNavigator
    from threading import Event
    nav=FarmNavigator(None,None,None,{},'Forza',Event())
    browser=NS(screen='challenge_browser',doc=Document([]))
    search=NS(screen='challenge_search',doc=Document([]))
    nav.observe=Mock(side_effect=[modal(),modal(2)])
    nav.key=Mock();nav.check=Mock();nav.ensure_home=Mock()
    nav.until=Mock(side_effect=lambda pred,*a,**kw:browser if pred(browser) else None)
    nav.wait=Mock(side_effect=[browser,search])
    monkeypatch.setattr('fh6.farm_search.reuse_search',lambda *args:True)
    nav.search_challenge(NS(share_code='155439962'))
    assert [c.args[0] for c in nav.key.call_args_list]==['enter','backspace']
    nav.ensure_home.assert_not_called()
