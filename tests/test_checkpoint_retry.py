import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fh6.session import Session, replace_checkpoint


class CheckpointRetryTests(unittest.TestCase):
    def test_report_receipt_survives_transient_reader_lock(self):
        from fh6.reporting import write_json
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)/'delivery.json'
            write_json(destination, {'earned': 266})
            original = Path.replace
            attempts = []
            def replace(source, target):
                attempts.append(source.read_bytes())
                if len(attempts) < 3:
                    raise PermissionError('reader holds receipt')
                return original(source, target)
            with patch.object(Path, 'replace', replace), patch('fh6.session.time.sleep'):
                write_json(destination, {'earned': 282, 'message_id': 'confirmed'})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(len(set(attempts)), 1)
            self.assertEqual(json.loads(destination.read_text()),
                             {'earned': 282, 'message_id': 'confirmed'})

    def test_reader_lock_retries_identical_checkpoint_without_losing_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Session(Path(folder)/'goal.json')
            session.start('Full pipeline', 47)
            original = Path.replace
            attempts = []
            def replace(source, destination):
                attempts.append(source.read_bytes())
                if len(attempts) < 3:
                    self.assertEqual(json.loads(destination.read_text())['rewards'], 0)
                    raise PermissionError('reader holds destination')
                return original(source, destination)
            with patch.object(Path, 'replace', replace), patch('fh6.session.time.sleep'):
                session.save(rewards=12, bought=13, phase='open_mastery')
            self.assertEqual(len(attempts), 3)
            self.assertEqual(len(set(attempts)), 1)
            saved = json.loads(session.path.read_text())
            self.assertEqual((saved['rewards'], saved['bought'], saved['phase']), (12, 13, 'open_mastery'))

    def test_persistent_lock_keeps_previous_checkpoint_and_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            destination, temporary = Path(folder)/'goal.json', Path(folder)/'goal.tmp'
            destination.write_text('old'); temporary.write_text('new')
            with patch.object(Path, 'replace', side_effect=PermissionError('locked')) as replace, patch('fh6.session.time.sleep'):
                with self.assertRaises(PermissionError):
                    replace_checkpoint(temporary, destination)
            self.assertEqual(replace.call_count, 21)
            self.assertEqual(destination.read_text(), 'old')
            self.assertEqual(temporary.read_text(), 'new')


if __name__ == '__main__':
    unittest.main()
