import tempfile
import threading
import unittest
from fh6.background import BackgroundStream
from fh6.analytics import Tracker


class BackgroundTests(unittest.TestCase):
    def test_queue_keeps_order_drains_and_survives_diagnostic_errors(self):
        stream=BackgroundStream();out=[]
        stream.submit(out.append,1)
        stream.submit(lambda:1/0)
        stream.submit(out.append,2)
        stream.close()
        self.assertEqual(out,[1,2]);self.assertEqual(stream.errors,1)
        self.assertFalse(stream.submit(out.append,3))

    def test_slow_diagnostics_never_block_submission_and_overflow_is_visible(self):
        gate=threading.Event();started=threading.Event();s=BackgroundStream(capacity=1)
        def slow(): started.set();gate.wait(3)
        s.submit(slow);self.assertTrue(started.wait(1))
        self.assertTrue(s.submit(lambda:None));self.assertFalse(s.submit(lambda:None))
        self.assertEqual(s.dropped,1);gate.set();s.close()

    def test_original_event_clock_excludes_queue_delay(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Tracker(folder,clock=lambda:1000)
            t.event('activity',True,event_time=1000)
            t.event('cycle_stage',dict(batch_id='a',cycle=1,phase='choose'),event_time=1002)
            t.event('cycle_stage',dict(batch_id='a',cycle=1,phase='mastery'),event_time=1007)
            self.assertEqual(t.data['cycle_work']['a:1']['steps']['choose'],5)
