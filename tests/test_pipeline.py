"""Pipeline ordering and interruption tests; no real game inputs."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fh6.pipeline import Pipeline
from fh6.session import Session


class PipelineTests(unittest.TestCase):
    def test_funded_collection_checkpoint_recovers_pause_before_purchase(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 1, funding=dict(
                id='funding', goal_id='goal', count=1, points=21,
                reserve=0, previous_session='old'))
            ledger = Mock(path=Path(folder)/'ledger.json')
            nav = Mock()
            nav.observe.return_value = SimpleNamespace(screen='pause_menu')
            nav.return_collection.side_effect = RuntimeError('recovered boundary')
            with patch('fh6.pipeline.purchase.buy') as buy:
                with self.assertRaisesRegex(RuntimeError, '^recovered boundary$'):
                    Pipeline(nav, ledger, session).run()
            nav.return_collection.assert_called_once_with()
            nav.collection.assert_not_called()
            buy.assert_not_called()
            self.assertEqual(session.data['phase'], 'collection')
            self.assertEqual(session.data['bought'], 0)
            self.assertEqual(session.data['completed'], 0)

    def test_funded_tree_reuses_twice_read_cars_tab_sp_budget(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 3, funding=dict(
                id='funding', goal_id='goal', count=3, points=63,
                reserve=0, previous_session='old'))
            session.save(phase='open_mastery', completed=1, bought=2, rewards=1)
            nav, ledger = Mock(), Mock(path=Path(folder)/'ledger.json')
            obs = SimpleNamespace(screen='mad_mike_mastery')
            nav.wait.return_value = obs
            nav.verify_fresh_mastery.side_effect = RuntimeError('stop after proof')
            with self.assertRaisesRegex(RuntimeError, 'stop after proof'):
                Pipeline(nav, ledger, session).run(max_cycles=1)
            nav.verify_fresh_mastery.assert_called_once_with(
                obs, verified_points=42)

    def test_unpurchased_buy_resume_restores_only_known_home_before_purchase(self):
        from unittest.mock import Mock
        for screen in ('cars', 'campaign', 'showroom', 'purchase_offer', 'unknown'):
            with self.subTest(screen=screen), tempfile.TemporaryDirectory() as folder:
                session = Session(Path(folder)/'session.json')
                session.start('Full pipeline', 1)
                session.save(phase='buy', purchase_before='older')
                path = Path(folder)/'ledger.json'
                path.write_text(json.dumps(dict(id='older', status='confirmed')))
                ledger, nav = Mock(path=path), Mock()
                nav.observe.return_value = SimpleNamespace(screen=screen)
                with patch('fh6.pipeline.purchase.buy', side_effect=RuntimeError('purchase boundary')) as buy:
                    with self.assertRaisesRegex(RuntimeError, '^purchase boundary$'):
                        Pipeline(nav, ledger, session).run()
                self.assertEqual(nav.collection.call_count, int(screen in {'cars', 'campaign', 'showroom'}))
                buy.assert_called_once()
                self.assertEqual(session.data['bought'], 0)

    def test_choice_on_used_car_reselects_newest_without_claiming(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 1)
            session.save(phase='choose', bought=1)
            nav, ledger = Mock(), Mock()
            obs = SimpleNamespace(result={'nodes': {str(i): {'state': 'owned'} for i in range(6)}})
            Pipeline(nav, ledger, session).resume_choice_from_tree(obs)
            nav.back_home.assert_called_once()
            nav.choose_car.assert_called_once()
            nav.verify_fresh_mastery.assert_not_called()
            self.assertEqual(session.data['phase'], 'open_mastery')
            self.assertEqual(session.data['bought'], 1)
            self.assertEqual(session.data['rewards'], 0)

    def test_ambiguous_tree_does_not_trigger_reselection(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 1)
            session.save(phase='choose', bought=1)
            nav = Mock()
            nav.verify_fresh_mastery.side_effect = RuntimeError('ambiguous tree')
            obs = SimpleNamespace(result={'nodes': {str(i): {'state': 'owned' if i else 'unknown'} for i in range(6)}})
            with self.assertRaisesRegex(RuntimeError, 'ambiguous tree'):
                Pipeline(nav, Mock(), session).resume_choice_from_tree(obs)
            nav.choose_car.assert_not_called()
            nav.back_home.assert_not_called()
            self.assertEqual(session.data['phase'], 'choose')

    def test_resume_inside_filter_returns_to_selection_without_rebuying(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 1)
            session.save(phase='choose', bought=1)
            ledger = Mock(path=Path(folder)/'ledger.json')
            nav = Mock()
            def wait(screens):
                if 'garage_filter' not in screens:
                    raise RuntimeError('filter excluded from resume screens')
                return SimpleNamespace(screen='garage_filter')
            nav.wait.side_effect = wait
            nav.choose_car.side_effect = RuntimeError('selection resumed')
            with patch('fh6.pipeline.purchase.buy') as buy:
                with self.assertRaisesRegex(RuntimeError, '^selection resumed$'):
                    Pipeline(nav, ledger, session).run()
                buy.assert_not_called()
            nav.choose_car.assert_called_once()
            self.assertEqual(session.data['bought'], 1)
            self.assertEqual(session.data['rewards'], 0)

    def test_pending_purchase_requires_visible_receipt_before_any_other_work(self):
        for visible in (False, True):
            with self.subTest(visible=visible), tempfile.TemporaryDirectory() as folder:
                session = Session(Path(folder)/'session.json')
                session.start('Full pipeline', 1)
                session.save(phase='buy', purchase_before='older')
                path = Path(folder)/'ledger.json'
                path.write_text(json.dumps(dict(id='pending-attempt', status='pending')))
                from unittest.mock import Mock
                ledger = Mock(path=path)
                nav = Mock()
                receipt = object()
                nav.wait.side_effect = [SimpleNamespace(frame=receipt)] if visible else RuntimeError('No success receipt')
                nav.check.side_effect = RuntimeError('stop after recovery check')
                pipeline = Pipeline(nav, ledger, session)
                with self.assertRaises(RuntimeError):
                    pipeline.run()
                nav.wait.assert_called_once_with('purchase_success')
                nav.key.assert_not_called()
                nav.collection.assert_not_called()
                if visible:
                    ledger.confirm.assert_called_once_with(receipt)
                    ledger.ready.assert_called_once()
                else:
                    ledger.confirm.assert_not_called()
                    ledger.ready.assert_not_called()

    def run_fake(self, folder, mode='Full pipeline', limit=2, session=None, stop=None):
        session = session or Session(Path(folder)/'session.json')
        session.start(mode, limit)
        actions = []
        ledger = SimpleNamespace(path=Path(folder)/'ledger.json', ready=lambda: None)

        def act(name):
            actions.append(name)
            if stop == name:
                raise RuntimeError('simulated stop')

        nav = SimpleNamespace(
            check=lambda: None, collection=lambda: act('collection'), paints=lambda: act('paints'),
            choose_car=lambda: act('choose'), open_mastery=lambda: act('open_mastery'),
            verify_fresh_mastery=lambda obs: act('fresh'), back_home=lambda: act('back_home'),
            wait=lambda screens: SimpleNamespace(screen='paints' if 'paints' in screens else 'mad_mike_mastery'))

        def buy(*args):
            act('buy')
            ledger.path.write_text(json.dumps(dict(id=str(session.data['bought']+1), status='confirmed')))
            if stop == 'after_confirmation':
                raise RuntimeError('simulated crash after confirmation')

        with patch('fh6.pipeline.purchase.buy', side_effect=buy), \
             patch('fh6.pipeline.purchase.acknowledge', side_effect=lambda nav: act('acknowledge')), \
             patch('fh6.pipeline.mastery.claim', side_effect=lambda nav: act('mastery')):
            try:
                Pipeline(nav, ledger, session).run()
            except RuntimeError as exc:
                return session, actions, str(exc)
        return session, actions, None

    def test_two_full_cycles_return_after_final_mastery(self):
        with tempfile.TemporaryDirectory() as folder:
            session, actions, error = self.run_fake(folder)
            self.assertIsNone(error)
            self.assertEqual(actions, ['collection', 'buy', 'acknowledge', 'choose',
                'open_mastery', 'fresh', 'mastery', 'back_home', 'collection'] * 2)
            self.assertEqual(session.data['completed'], 2)
            self.assertEqual(session.data['rewards'], 2)
            self.assertEqual(session.data['phase'], 'complete')

    def test_buy_only_never_enters_mastery(self):
        with tempfile.TemporaryDirectory() as folder:
            session, actions, error = self.run_fake(folder, 'Buy only')
            self.assertIsNone(error)
            self.assertEqual(actions.count('buy'), 2)
            self.assertNotIn('mastery', actions)
            self.assertEqual(session.data['rewards'], 0)

    def test_resume_confirmed_purchase_never_buys_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            session, _, error = self.run_fake(folder, limit=1, stop='after_confirmation')
            self.assertIsNotNone(error)
            self.assertEqual(session.data['phase'], 'buy')
            session = Session(Path(folder)/'session.json')
            session, actions, error = self.run_fake(folder, limit=1, session=session)
            self.assertIsNone(error)
            self.assertNotIn('buy', actions)
            self.assertEqual(session.data['bought'], 1)

    def test_failed_choice_blocks_next_purchase(self):
        with tempfile.TemporaryDirectory() as folder:
            session, actions, error = self.run_fake(folder, stop='choose')
            self.assertIsNotNone(error)
            self.assertEqual(session.data['phase'], 'choose')
            self.assertEqual(actions.count('buy'), 1)
            self.assertNotIn('mastery', actions)
            self.assertEqual(session.data['completed'], 0)

    def test_final_return_resume_cannot_buy_an_extra_car(self):
        with tempfile.TemporaryDirectory() as folder:
            session, _, error = self.run_fake(folder, limit=1, stop='back_home')
            self.assertIsNotNone(error)
            self.assertEqual(session.data['phase'], 'return')
            session, actions, error = self.run_fake(folder, limit=1, session=Session(session.path))
            self.assertIsNone(error)
            self.assertEqual(actions, ['back_home', 'collection'])
            self.assertEqual(session.data['completed'], 1)
            self.assertEqual(session.data['rewards'], 1)

    def test_unfinished_session_cannot_change_mode_or_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'session.json')
            session.start('Full pipeline', 2)
            with self.assertRaises(RuntimeError):
                session.start('Buy only', 2)
            with self.assertRaises(RuntimeError):
                session.start('Full pipeline', 3)


if __name__ == '__main__':
    unittest.main()
