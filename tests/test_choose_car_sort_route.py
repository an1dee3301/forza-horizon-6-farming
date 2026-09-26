"""The live sort route avoids a pointer click that has failed in production."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from fh6.navigation import Navigator


def test_choose_car_uses_verified_keyboard_sort_then_checks_new_car():
    grid = SimpleNamespace(screen="garage_grid", doc=Mock(lines=[]), result={})
    dialog = SimpleNamespace(screen="sort_selection", doc=Mock())
    dialog.doc.has.return_value = True
    nav = object.__new__(Navigator)
    nav.fast_navigation = True
    nav.garage_recent_sort_verified = False
    nav.wait = Mock(side_effect=[grid, dialog, grid, grid])
    nav.key = Mock()
    nav.pause = Mock()
    nav.emit = Mock()
    nav.click_label = Mock()
    nav.keyboard_select = Mock()
    nav.enter_fresh_car = Mock()

    with patch("fh6.navigation.set_favorites", return_value=grid):
        nav.choose_car()

    nav.keyboard_select.assert_called_once_with("sort_selection", "Recently Added")
    nav.click_label.assert_not_called()
    nav.enter_fresh_car.assert_called_once_with(grid)
    assert nav.garage_recent_sort_verified is True
