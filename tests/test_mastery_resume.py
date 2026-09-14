import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from fh6.farming import FarmNavigator
from fh6.ocr import Document, Text


class MasteryResumeTests(unittest.TestCase):
    def nav(self, name='1974 Mazda #123 Mad Mike 808', screen='pause_menu'):
        nav = FarmNavigator.__new__(FarmNavigator)
        obs = SimpleNamespace(screen=screen, doc=Document([Text(name,(570,110,600,35))]))
        nav.observe=Mock(return_value=obs)
        nav.ensure_home=Mock()
        nav.until=Mock(return_value=obs)
        nav.open_mastery=Mock()
        nav.emit=Mock()
        return nav

    def test_pause_menu_reopens_current_car_tree(self):
        nav=self.nav()
        nav.resume_mastery()
        nav.ensure_home.assert_called_once()
        nav.open_mastery.assert_called_once()

    def test_current_tree_needs_no_navigation(self):
        nav=self.nav(screen='mad_mike_mastery')
        nav.resume_mastery()
        nav.ensure_home.assert_not_called()
        nav.open_mastery.assert_not_called()

    def test_wrong_car_cannot_resume_or_buy(self):
        nav=self.nav(name='Subaru 22B')
        with self.assertRaisesRegex(RuntimeError,'current car'):
            nav.resume_mastery()
        nav.ensure_home.assert_not_called()
        nav.open_mastery.assert_not_called()

    def test_changed_car_after_home_blocks_claim(self):
        nav=self.nav()
        nav.until.return_value=SimpleNamespace(doc=Document([Text('Subaru 22B',(100,40,500,35))]))
        with self.assertRaisesRegex(RuntimeError,'car changed'):
            nav.resume_mastery()
        nav.open_mastery.assert_not_called()
