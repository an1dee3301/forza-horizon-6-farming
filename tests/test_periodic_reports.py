import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fh6.discord_reports import deliver, periodic_due
from fh6.reporting import payload, snapshot
from fh6.report_charts import render_charts
from fh6.operations_metrics import summarize


class PeriodicReports(unittest.TestCase):
    def test_periodic_photo_uses_approved_source_metadata_not_latest_worker_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            data = snapshot(Path(folder), active=True, game='running')
            data.update(goal_id='mission', earned=50)
            original_time = '2026-09-12T10:00:00+00:00'
            def approved(*, goal_id, metadata_out):
                self.assertEqual(goal_id, 'mission')
                metadata_out.update(screen='pause_menu', earned=42, observed_at=original_time,
                                    menu_policy='my_horizon_only_v2')
                return b'approved home', original_time
            with patch('fh6.discord_reports.RUNS', Path(folder)), \
                 patch('fh6.discord_reports.STATE', Path(folder)/'delivery.json'), \
                 patch('fh6.discord_reports.read_json', return_value={'screen':'cars', 'earned':50}), \
                 patch('fh6.report_images.evidence', side_effect=approved) as evidence, \
                 patch('fh6.discord_reports.render', return_value=b'board'), \
                 patch('fh6.discord_reports.secrets.webhook', return_value='private'), \
                 patch('fh6.discord_reports.send', return_value={'message_id':'confirmed'}) as send:
                self.assertEqual(deliver(data, periodic=True)['message_id'], 'confirmed')
                evidence.assert_called_once()
                selected = send.call_args.args[1]['game_capture']
                self.assertEqual(selected['screen'], 'pause_menu')
                self.assertEqual(selected['earned'], 42)
                self.assertEqual(selected['observed_at'], original_time)
                self.assertEqual(send.call_args.kwargs['game_image'], (b'approved home', original_time))

    def test_cadence_never_sends_early_or_depends_on_rewards(self):
        self.assertFalse(periodic_due(59.9, 60))
        self.assertTrue(periodic_due(60, 60))
        self.assertTrue(periodic_due(120, 60))
        self.assertFalse(periodic_due(5, 0))

    def test_unchanged_progress_and_pending_account_without_photo_still_send(self):
        with tempfile.TemporaryDirectory() as folder:
            data = snapshot(Path(folder), active=True, game='running')
            data['account'] = {'checkpoint': {'status': 'Pending'}}
            with patch('fh6.discord_reports.RUNS', Path(folder)), \
                 patch('fh6.discord_reports.STATE', Path(folder)/'delivery.json'), \
                 patch('fh6.discord_reports.read_json', return_value={'snapshot': data}), \
                 patch('fh6.report_images.evidence', return_value=None), \
                 patch('fh6.discord_reports.secrets.webhook', return_value='private'), \
                 patch('fh6.discord_reports.send', return_value={'message_id':'confirmed'}) as send:
                self.assertEqual(deliver(data, periodic=True)['message_id'], 'confirmed')
                self.assertEqual(send.call_args.args[1]['report_kind'], 'status')
                self.assertIsNone(send.call_args.kwargs['game_image'])
                body = payload(send.call_args.args[1])
                self.assertIn('MINUTE STATUS', body['embeds'][0]['title'])
                self.assertTrue(all(not f['inline'] for f in body['embeds'][0]['fields']))
                self.assertEqual(body['allowed_mentions'], {'parse': []})

    def test_focused_charts_rotate_and_fit_discord_ten_embed_limit(self):
        source = {'goal_id':'test', 'cycles':[{'elapsed_seconds':50,'steps':{'choose':20}}]}
        data = {'goal_id':'test','earned':1,'target':1000,'charts':source,
                'analytics':{'operations':summarize({'rewards':1}, source)}}
        seen = set()
        for page in range(3):
            cards = render_charts(dict(data, chart_page=page), focused=True)
            self.assertEqual(len(cards), 8)  # + overview + optional garage = 10
            names = {c[0] for c in cards}
            self.assertTrue({'chart_00.png','chart_01.png','chart_06.png','chart_11.png'} <= names)
            seen |= names
            for name, blob, title in cards:
                with Image.open(io.BytesIO(blob)) as image:
                    self.assertGreater(image.width, 800)
                    self.assertLess(image.height, 750)
        self.assertEqual(len(seen), 16)
