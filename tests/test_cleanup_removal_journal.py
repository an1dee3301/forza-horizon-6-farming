import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fh6.analytics import Tracker
from fh6.cleanup_removal_journal import RemovalJournal
from fh6.garage_cleanup import GarageCleanup


def fixture(tmp_path):
    tracker = Tracker(tmp_path)
    tracker.data['goal_id'] = 'goal'
    nav = Mock()
    nav.setup_checks.identity.return_value = ['pid:creation']
    journal = RemovalJournal(tracker)
    row = journal.begin(nav)
    return tracker, nav, journal, row


def test_acknowledged_then_crash_commits_once_without_input(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.submitted(row)
    journal.acknowledged(row, nav)
    resumed = Tracker(tmp_path)
    resumed.data['goal_id'] = 'goal'
    nav.setup_checks.identity.return_value = ['new:process']
    assert GarageCleanup(nav, resumed).recover_pending_removal() == 1
    assert resumed.data['garage_cleanup']['removed'] == 1
    nav.wait.assert_not_called()
    nav.key.assert_not_called()
    assert GarageCleanup(nav, resumed).recover_pending_removal() == 0


def test_crash_after_journal_append_before_pending_clear_is_idempotent(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.submitted(row)
    journal.acknowledged(row, nav)
    with patch.object(journal, 'finish', side_effect=RuntimeError('crash')):
        with pytest.raises(RuntimeError):
            journal.commit(row)
    resumed = Tracker(tmp_path)
    resumed.data['goal_id'] = 'goal'
    assert GarageCleanup(nav, resumed).recover_pending_removal() == 0
    assert resumed.data['garage_cleanup']['removed'] == 1
    assert len((tmp_path/'analytics_garage_cleanup.jsonl').read_text().splitlines()) == 1


def test_submitted_same_process_fresh_grid_acknowledged(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.submitted(row)
    nav.wait.return_value = SimpleNamespace(screen='garage_grid')
    assert GarageCleanup(nav, tracker).recover_pending_removal() == 1
    assert nav.wait.call_args.kwargs['stable_frames'] == 2
    nav.key.assert_not_called()


def test_actual_stable_yes_timeout_remains_uncounted(tmp_path):
    # Actual 17:13:48 evidence is a fully recognized, still-open Yes dialog.
    evidence = {'last_screen': 'remove_confirmation',
                'last_observation_text': ['Remove Car From Garage', 'No', 'Yes']}
    assert evidence['last_screen'] == 'remove_confirmation'
    assert 'Remove Car From Garage' in evidence['last_observation_text']
    assert 'Yes' in evidence['last_observation_text']
    tracker, nav, journal, row = fixture(tmp_path)
    journal.submitted(row)
    nav.wait.side_effect = RuntimeError('Timed out waiting for garage_grid; no input retry')
    assert GarageCleanup(nav, tracker).recover_pending_removal() == 0
    assert tracker.data.get('garage_cleanup', {}).get('removed', 0) == 0
    nav.key.assert_not_called()
    nav.keyboard_select.assert_not_called()
    assert journal.read() is None
    outcome = json.loads(next((tmp_path/'garage_removal_operations').glob('*.json')).read_text())
    assert outcome['outcome'] == 'unresolved_acknowledgement_timeout'


@pytest.mark.parametrize('state', ['prepared', 'submitted'])
def test_changed_process_never_counts_or_inputs(tmp_path, state):
    tracker, nav, journal, row = fixture(tmp_path)
    if state == 'submitted':
        journal.submitted(row)
    nav.setup_checks.identity.return_value = ['other:process']
    assert GarageCleanup(nav, tracker).recover_pending_removal() == 0
    nav.wait.assert_not_called()
    nav.key.assert_not_called()
    assert not (tmp_path/'analytics_garage_cleanup.jsonl').exists()


def test_unacknowledged_cannot_commit(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    with pytest.raises(RuntimeError, match='acknowledged'):
        journal.commit(row)


def test_controller_recovers_before_menu_or_filter_input(tmp_path):
    from fh6.controller import Controller
    tracker, nav, journal, row = fixture(tmp_path)
    controller = Controller.__new__(Controller)
    controller.background = None
    controller.analytics = tracker
    nav.wait.return_value = SimpleNamespace(screen='remove_confirmation')
    order = Mock()
    with patch('fh6.garage_cleanup.GarageCleanup') as factory, \
            patch('fh6.mad_mike_inventory.prepare_filter') as prepare:
        cleanup = factory.return_value
        cleanup.recover_pending_removal.return_value = 0
        cleanup.run.return_value = 1
        order.attach_mock(cleanup.recover_pending_removal, 'recover')
        order.attach_mock(nav.wait, 'wait')
        order.attach_mock(cleanup.return_to_grid, 'cancel')
        order.attach_mock(prepare, 'filter')
        assert controller.terminal_cleanup(nav, Mock()) == 1
        assert [item[0] for item in order.mock_calls] == ['recover', 'wait', 'cancel', 'filter']


def test_duplicate_commit_in_same_tracker(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.acknowledged(row, nav)
    assert journal.commit(row) == 1
    assert journal.commit(row) == 0
    assert tracker.data['garage_cleanup']['removed'] == 1


def test_failed_durable_append_does_not_increment_and_retry_commits_once(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.acknowledged(row, nav)
    with patch.object(tracker, 'append', side_effect=OSError('disk unavailable')):
        with pytest.raises(OSError):
            journal.commit(row)
    assert tracker.data.get('garage_cleanup', {}).get('removed', 0) == 0
    assert journal.read()['state'] == 'acknowledged'
    assert journal.commit(row) == 1
    assert tracker.data['garage_cleanup']['removed'] == 1


def test_wrong_goal_preserves_unresolved_operation_without_count(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    journal.submitted(row)
    tracker.data['goal_id'] = 'different'
    assert GarageCleanup(nav, tracker).recover_pending_removal() == 0
    nav.wait.assert_not_called()
    nav.key.assert_not_called()
    assert not (tmp_path/'analytics_garage_cleanup.jsonl').exists()


def test_crash_after_yes_before_submitted_save_reads_only_then_commits(tmp_path):
    tracker, nav, journal, row = fixture(tmp_path)
    # The intent is durable; Yes may have occurred before submitted could save.
    assert journal.read()['state'] == 'prepared'
    nav.wait.return_value = SimpleNamespace(screen='garage_grid')
    assert GarageCleanup(nav, tracker).recover_pending_removal() == 1
    nav.key.assert_not_called()
    nav.keyboard_select.assert_not_called()
    assert tracker.data['garage_cleanup']['removed'] == 1
