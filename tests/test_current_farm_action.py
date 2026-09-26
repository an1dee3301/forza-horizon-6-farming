"""Current-car menus can be canceled without selecting any removal action."""
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest
import forza_cycle as core
from fh6.farming import FarmNavigator
from fh6.ocr import Document, Text
from fh6.pause_farm import select_from_pause


def action(get_in=False, cancels=1):
    lines=[Text('Select An Action',(730,414,430,50)),
           Text('Remove From Favorites',(800,480,300,35)),
           Text('View Car',(840,530,200,30)),
           Text('View History',(840,590,200,30))]
    if get_in:
        lines.append(Text('Get In Car',(645,425,180,30)))
    for i in range(cancels):
        lines.append(Text('Cancel',(270+i*200,988,100,25)))
    return NS(screen='car_action',doc=Document(lines))


def screen(name):
    lines=[Text('BUY & SELL',(500,170,140,25)),
           Text('CUSTOMIZABLE GARAGE',(740,170,280,25))] if name=='cars' else []
    return NS(screen=name,doc=Document(lines))


@pytest.mark.parametrize('get_in',[False,True])
def test_home_recovery_uses_two_fresh_proofs_and_only_escape(get_in):
    nav=FarmNavigator(None,None,None,{},'Forza',Event())
    nav.observe=Mock(side_effect=[action(get_in),action(get_in),action(get_in),
        *[screen('garage_grid') for _ in range(3)],*[screen('cars') for _ in range(3)]])
    nav.key=Mock();nav.pause=Mock();nav.check=Mock()
    captured=[]
    nav.key.side_effect=lambda key:captured.append(nav.observe.call_count)
    nav.ensure_home()
    assert [c.args[0] for c in nav.key.call_args_list]==['esc','esc']
    assert captured==[3,6]


@pytest.mark.parametrize('cancels',[0,2])
def test_home_invalid_cancel_never_sends_input(cancels):
    nav=FarmNavigator(None,None,None,{},'Forza',Event())
    nav.observe=Mock(side_effect=[action(),action(cancels=cancels),core.MasteryStopped('F7')])
    nav.key=Mock();nav.pause=Mock();nav.check=Mock()
    with pytest.raises(core.MasteryStopped):
        nav.ensure_home()
    nav.key.assert_not_called()


@pytest.mark.parametrize('get_in',[False,True])
def test_pause_preserves_public_favorites_route_and_normal_delivery(get_in):
    nav=Mock();nav.timeout=5
    first=action(get_in)
    nav.until.side_effect=[first,screen('pause_menu'),screen('pause_menu')]
    nav.is_roam.return_value=False
    nav.wait.side_effect=[screen('garage_grid'),first,screen('garage_grid')]
    profile=object()
    with patch('fh6.pause_farm.pause_ready',return_value=True), \
         patch('fh6.pause_farm.current_farm_car',return_value=False), \
         patch('fh6.garage.set_favorites') as favorites:
        result=select_from_pause(nav,profile)
    favorites.assert_called_once_with(nav,True)
    nav.wait_farm_car_card.assert_called_once_with(profile)
    assert result is get_in
    assert [c.args[0] for c in nav.key.call_args_list]==(['enter'] if get_in else ['enter','esc'])
    assert [c.args[1] for c in nav.click_label.call_args_list]==(['Change','Get In Car'] if get_in else ['Change'])
    if not get_in:
        proof=nav.wait.call_args_list[1]
        assert proof.kwargs['stable_frames']==2
        assert proof.kwargs['predicate'](first)
        assert not proof.kwargs['predicate'](action(cancels=0))
        assert not proof.kwargs['predicate'](action(cancels=2))
