"""No game inputs: synchronization must outrank priority, retries and timers."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import forza_cycle as core
from fh6.cloud_sync import SyncGuard, SyncPending, sync_state, confirm_current_sync
from fh6.game_lifecycle import GameLifecycle, GameCrashed
from fh6.navigation import Navigator
from fh6.ocr import Document, Text


def doc(*lines):
    return Document([Text(s, (50, 800+i*40, 200, 25)) for i, s in enumerate(lines)])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.running = threading.Event()
        self.running.set()
        self.windows = []
        self.guard = SyncGuard(lambda: self.windows, self.running,
                               path=Path(self.folder.name)/'sync.json')
        self.now = 0
        def sleep(seconds):
            self.now += seconds
        self.backend = Mock()
        self.backend.identity.return_value = ['game:creation1']
        self.life = GameLifecycle(self.running, backend=self.backend, clock=lambda:self.now,
            sleep=sleep, startup_timeout=1, path=Path(self.folder.name)/'recovery.json')
        self.life.sync_guard = self.guard
        self.nav = Mock(title='Forza Horizon 6')
        self.nav.is_home.side_effect = lambda o:o.screen == 'cars'
        self.nav.is_roam.return_value = False
        self.nav.observe_sync.return_value = SimpleNamespace(screen='cars', doc=doc())
        p = patch('fh6.game_lifecycle.core.foreground_title', return_value='Forza Horizon 6')
        p.start()
        self.addCleanup(p.stop)

    def test_occluded_dialog_blocks_focus_startup_and_termination_even_if_backup_off(self):
        self.windows = [123]
        for enabled in (True, False):
            self.life.enabled = enabled
            for action in (lambda:self.life.ensure(self.nav), self.life.restore_focus,
                           lambda:self.life.recover(GameCrashed('stalled'), self.nav)):
                with self.assertRaises(SyncPending):
                    action()
        self.backend.activate.assert_not_called()
        self.backend.launch.assert_not_called()
        self.backend.terminate_crashed.assert_not_called()
        self.assertFalse(self.life.is_crash(SyncPending('sync')))

    def test_wait_exceeds_timeout_and_requires_explicit_completion_then_stable_game(self):
        self.guard.windows = lambda:[123] if self.now < 8 else []
        self.nav.observe_sync.side_effect = lambda: SimpleNamespace(screen='cars',
            doc=doc('Sync complete') if self.now >= 8 else doc('Syncing data'))
        self.life.wait_sync(self.nav)
        self.assertGreaterEqual(self.now, 9)
        self.assertGreaterEqual(self.nav.observe_sync.call_count, 3)
        self.nav.key.assert_not_called()
        self.backend.activate.assert_not_called()
        self.backend.launch.assert_not_called()
        self.backend.terminate_crashed.assert_not_called()
        self.assertFalse(self.guard.path.exists())

    def test_f7_cancels_wait_but_does_not_clear_pending_sync(self):
        self.windows = [123]
        self.life.sleep = lambda _:self.running.clear()
        with self.assertRaises(core.MasteryStopped):
            self.life.wait_sync(self.nav)
        self.assertTrue(self.guard.path.exists())
        self.nav.key.assert_not_called()

    def test_stable_playable_menu_for_current_process_releases_stale_sync_gate(self):
        self.life.wait_sync(self.nav)
        self.assertGreaterEqual(self.nav.observe_sync.call_count, 3)
        self.assertFalse(self.guard.pending)
        self.assertIn('stable playable', self.guard.evidence)
        self.nav.key.assert_not_called()

    def test_stable_pause_menu_for_current_process_releases_stale_sync_gate(self):
        self.nav.observe_sync.side_effect = lambda:SimpleNamespace(screen='pause_menu',
            doc=doc('MY HORIZON', 'CREATIVE HUB'))
        self.life.wait_sync(self.nav)
        self.assertGreaterEqual(self.nav.observe_sync.call_count, 3)
        self.assertFalse(self.guard.pending)
        self.assertIn('stable playable pause_menu', self.guard.evidence)
        self.nav.key.assert_not_called()

    def test_startup_continue_is_selected_once_before_sync_gate_accepts_game_menu(self):
        continue_screen = SimpleNamespace(screen='continue', doc=doc('Continue', 'Options', 'Exit'), frame=object())
        pause = SimpleNamespace(screen='pause_menu', doc=doc('MY HORIZON', 'CREATIVE HUB'), frame=object())
        observations = [continue_screen, continue_screen, pause, pause, pause]
        self.nav.observe_sync.side_effect = observations
        with (
                patch('fh6.navigation.label_focused', return_value=True),
                patch('pyautogui.keyDown') as key_down,
                patch('pyautogui.keyUp') as key_up):
            self.life.wait_sync(self.nav)
        self.assertEqual(key_down.call_args_list, [unittest.mock.call('enter')])
        self.assertEqual(key_up.call_args_list, [unittest.mock.call('enter')])
        self.assertIn('stable playable pause_menu', self.guard.evidence)
        self.assertFalse(self.guard.pending)

    def test_wait_restores_game_focus_when_no_sync_window_is_visible(self):
        calls = {'count': 0}
        def foreground():
            calls['count'] += 1
            return 'ChatGPT' if calls['count'] == 1 else 'Forza Horizon 6'
        with patch('fh6.game_lifecycle.core.foreground_title', side_effect=foreground):
            self.life.wait_sync(self.nav)
        self.backend.activate.assert_called_once()
        self.nav.key.assert_not_called()

    def test_wait_does_not_activate_game_while_sync_window_is_visible(self):
        self.windows = [123]
        self.life.sleep = lambda _:self.running.clear()
        with self.assertRaises(core.MasteryStopped):
            self.life.wait_sync(self.nav)
        self.backend.activate.assert_not_called()

    def test_sync_approval_is_bound_to_game_process_and_revoked_by_new_dialog(self):
        with self.assertRaises(SyncPending):
            self.guard.require_verified(['game:creation1'])
        self.guard.observe_completion(doc('Sync complete'))
        self.assertTrue(self.guard.ready())
        self.guard.require_verified(['game:creation1'])
        restarted = SyncGuard(lambda:[], self.running, path=self.guard.path)
        restarted.require_verified(['game:creation1'])
        self.windows = [123]
        with self.assertRaises(SyncPending):
            self.guard.check()
        self.assertIsNone(self.guard.evidence)
        self.windows = []
        self.assertFalse(self.guard.ready())

    def test_worker_restart_and_disappearing_dialog_alone_do_not_unlock_inputs(self):
        self.guard.block('sync')
        restarted = SyncGuard(lambda:[], self.running, path=self.guard.path)
        with self.assertRaises(SyncPending):
            restarted.check()
        nav = Navigator(None, None, None, {}, 'Forza', self.running)
        nav.sync_guard = restarted
        nav.restore_focus = Mock()
        with self.assertRaises(SyncPending):
            nav.check()
        nav.restore_focus.assert_not_called()

    def test_old_process_confirmation_cannot_authorize_a_new_process(self):
        self.guard.block('startup')
        confirm_current_sync(self.guard.path)
        self.assertTrue(self.guard.ready())
        self.guard.require_verified(['123:creation-old'])
        for guard in (self.guard, SyncGuard(lambda:[], self.running, path=self.guard.path)):
            with self.assertRaises(SyncPending):
                guard.require_verified(['123:creation-new'])

    def test_new_sync_request_does_not_accept_an_old_confirmation(self):
        self.guard.block('first startup')
        confirm_current_sync(self.guard.path)
        old_answer = self.guard.path.with_suffix('.confirmed.json').read_text(encoding='utf-8')
        self.assertTrue(self.guard.ready())
        self.guard.block('new cloud dialog')
        self.guard.path.with_suffix('.confirmed.json').write_text(old_answer, encoding='utf-8')
        self.assertFalse(self.guard.ready())
        self.assertTrue(self.guard.pending)

    def test_sync_error_offline_and_cancel_dialogs_never_count_as_completion(self):
        for text in ("We can't sync your data with the cloud right now.", 'Stop syncing data?',
                     'Play offline', 'Syncing data 100%', 'Which save do you want to use?'):
            with self.subTest(text=text):
                self.assertIsNotNone(sync_state(doc(text)))
                self.nav.observe_sync.return_value = SimpleNamespace(screen='cars', doc=doc(text))
                self.life.sleep = lambda _:self.running.clear()
                with self.assertRaises(core.MasteryStopped):
                    self.life.wait_sync(self.nav)
                self.assertTrue(self.guard.pending)
                self.running.set()
        self.nav.key.assert_not_called()

    def test_reappearing_dialog_cannot_clear_checkpoint(self):
        self.guard.block('sync')
        self.windows = [123]
        self.assertFalse(self.guard.ready())
        self.assertTrue(self.guard.path.exists())

    def test_final_progress_requires_dialog_to_close_before_automatic_release(self):
        self.guard.block('syncing')
        self.windows = [123]
        self.guard.observe_completion(doc('Syncing data', '100%'))
        self.assertFalse(self.guard.ready())
        self.windows = []
        self.assertTrue(self.guard.ready())
        self.assertIn('100%', self.guard.evidence)

    def test_cancel_prompt_invalidates_previously_seen_final_progress(self):
        self.guard.block('syncing')
        self.guard.observe_completion(doc('Syncing data', '100%'))
        self.guard.observe_completion(doc('Stop syncing data?'))
        self.assertFalse(self.guard.ready())

    def test_sync_retry_invalidates_old_completion_until_fresh_final_progress(self):
        for old_completion in (doc('Syncing data', '100%'), doc('Sync complete')):
            with self.subTest(old_completion=[line.text for line in old_completion.lines]):
                self.guard.block('syncing')
                self.guard.observe_completion(old_completion)
                self.guard.observe_completion(doc('Syncing data', '25%'))
                self.assertFalse(self.guard.ready())
                self.assertTrue(self.guard.path.exists())
                self.guard.observe_completion(doc('Syncing data', '100%'))
                self.assertTrue(self.guard.ready())

    def test_partial_second_sync_stage_cannot_reuse_a_100_percent_stage(self):
        self.guard.block('syncing')
        self.guard.observe_completion(doc('Syncing data', '100%'))
        self.guard.observe_completion(doc('Syncing data', '100%', '25%'))
        self.assertFalse(self.guard.ready())

    def test_process_change_during_sync_revokes_progress_and_confirmation(self):
        self.guard.block('sync')
        self.guard.observe_wait_identity(['game:creation1'])
        self.guard.observe_completion(doc('Syncing data', '100%'))
        confirm_current_sync(self.guard.path)
        request = self.guard.path.read_text()
        self.assertTrue(self.guard.observe_wait_identity(['game:creation2']))
        self.assertNotEqual(self.guard.path.read_text(), request)
        self.assertFalse(self.guard.saw_final_progress)
        self.assertFalse(self.guard.confirmation())
        self.assertFalse(self.guard.ready())

    def test_wait_completion_is_bound_before_next_mission_identity_check(self):
        self.guard.block('sync')
        self.guard.observe_wait_identity(['game:creation1'])
        self.guard.observe_completion(doc('Syncing data', '100%'))
        self.assertTrue(self.guard.ready())
        restarted = SyncGuard(lambda:[], self.running, path=self.guard.path)
        restarted.require_verified(['game:creation1'])
        with self.assertRaises(SyncPending):
            self.guard.require_verified(['game:creation2'])

    def test_no_game_process_cannot_release_sync_wait(self):
        self.guard.block('sync')
        self.guard.observe_wait_identity([])
        self.guard.observe_completion(doc('Sync complete'))
        self.assertFalse(self.guard.ready())

    def test_playable_ui_proof_is_rejected_without_process_or_with_sync_window(self):
        self.assertFalse(self.guard.playable_ui_complete([], 'cars'))
        self.windows = [123]
        self.assertFalse(self.guard.playable_ui_complete(['game:creation1'], 'cars'))

    def test_live_wait_discards_old_completion_then_accepts_stable_new_playable_game(self):
        self.guard.windows = lambda:[123] if self.now < 1 else []
        self.backend.identity.side_effect = lambda:['game:creation1' if self.now < 1 else 'game:creation2']
        self.nav.observe_sync.side_effect = lambda:SimpleNamespace(screen='cars',
            doc=doc('Syncing data', '100%') if self.now < 1 else doc())
        def stop_after_wait(seconds):
            self.now += seconds
            if self.now >= 5:
                self.running.clear()
        self.life.sleep = stop_after_wait
        self.life.wait_sync(self.nav)
        self.assertFalse(self.guard.pending)
        self.assertIn('stable playable', self.guard.evidence)
        self.nav.key.assert_not_called()
        self.backend.activate.assert_not_called()
        self.backend.launch.assert_not_called()

    def test_full_owned_startup_can_verify_sync_but_attached_home_cannot(self):
        self.guard.native_startup_complete(False, set())
        self.assertIsNone(self.guard.evidence)
        self.guard.native_startup_complete(True, {'start'})
        self.assertIsNone(self.guard.evidence)
        self.guard.native_startup_complete(True, {'start', 'continue'})
        self.assertIsNotNone(self.guard.evidence)
        self.guard.block('sync reopened')
        with self.assertRaises(SyncPending):
            self.guard.native_startup_complete(True, {'start', 'continue'})

    def test_purchase_and_mastery_modules_obey_sync_gate_before_sending_inputs(self):
        self.windows = [123]
        self.running.input_guard = self.guard.check
        inputs = Mock()
        with patch.dict('sys.modules', {'pyautogui':inputs}):
            for operation in (
                lambda:core.purchase_once(Mock(), Mock(), {}, 'Forza Horizon 6', self.running, Mock()),
                lambda:core.mastery_once(Mock(), Mock(), {}, 'Forza Horizon 6', self.running),
                lambda:core.return_to_collection(Mock(), Mock(), {}, 'Forza Horizon 6', self.running)):
                with self.assertRaises(SyncPending):
                    operation()
        inputs.keyDown.assert_not_called()
        inputs.mouseDown.assert_not_called()


if __name__ == '__main__':
    unittest.main()
