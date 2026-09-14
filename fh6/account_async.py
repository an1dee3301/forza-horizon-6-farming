"""Bounded background account OCR; never wait for it before a game input."""
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np

from .ocr import WindowsOCR
from .reporting import AccountObserver, RUNS, now
from .account_header import ACCOUNT_BOX, compact_header, compact_capture_box, cache_strip


class AsyncAccountObserver:
    needs_confirmation = False
    confirmation_attempts = 0
    visible = staticmethod(AccountObserver.visible)

    def __init__(self, path=RUNS/'account_observed.json', *, reader_factory=WindowsOCR,
                 observer_factory=AccountObserver, capacity=8):
        self.path = path
        from .reporting import read_json
        self.gamertag = read_json(path).get('gamertag')
        self.reader_factory, self.observer_factory = reader_factory, observer_factory
        self.queue = queue.Queue(maxsize=capacity)
        self.event = None
        self.closed = threading.Event()
        self.last_capture = 0
        self.submitted = self.processed = self.dropped = self.errors = 0
        self.thread = threading.Thread(target=self._work, name='FH6 account OCR', daemon=True)
        self.thread.start()

    def _offer(self, item):
        if self.closed.is_set():
            return
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                self.dropped += 1

    def begin_event(self, key, label):
        if self.event and self.event[0] == key:
            return
        self.event = (key, label, now())
        self.last_capture = 0
        self._offer((self.event, None, None))

    def observe(self, obs, reader=None, force=False):
        if not self.visible(obs) or time.monotonic()-self.last_capture < .12:
            return
        self.last_capture = time.monotonic()
        # Only account pixels are retained. The game frame has already passed
        # the foreground/sync checks; the worker never captures or navigates.
        x, y, w, h = ACCOUNT_BOX
        card=compact_header(obs.doc,self.gamertag)
        compact_box=compact_capture_box(obs.doc,self.gamertag)
        if card:x,y,w,h=card['box']
        elif compact_box:x,y,w,h=compact_box
        header = obs.frame[y:y+h, x:x+w].copy()
        captured = SimpleNamespace(header=header, doc=obs.doc, screen=obs.screen,
                                   box=(x,y,w,h),account_layout='compact' if card or compact_box else 'horizontal')
        self.submitted += 1
        self._offer((self.event, captured, now()))

    def _work(self):
        reader = None
        try:
            # Windows OCR's event loop belongs exclusively to this thread.
            reader = self.reader_factory()
            observer = self.observer_factory(self.path)
            while not self.closed.is_set():
                try:
                    event, captured, stamp = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                try:
                    if event:
                        observer.begin_event(event[0], event[1], requested_at=event[2])
                    if captured is not None:
                        frame = np.zeros((1080,1920,3), dtype=np.uint8)
                        x, y, w, h = captured.box
                        frame[y:y+h, x:x+w] = captured.header
                        obs = SimpleNamespace(frame=frame, doc=captured.doc, screen=captured.screen,
                                              account_layout=captured.account_layout)
                        observer.observe(obs, reader=reader, force=True, observed_at=stamp)
                        if isinstance(getattr(observer,'data',None),dict):
                            cache_strip(frame,captured.doc,observer.data,stamp,self.path.parent,captured.account_layout)
                        self.processed += 1
                except Exception:
                    self.errors += 1
                finally:
                    self.queue.task_done()
        except Exception:
            self.errors += 1
        finally:
            if reader:
                reader.close()
            while True:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    break

    def close(self):
        self.closed.set()
        # Inputs are already stopped. Finish at most the in-flight OCR before
        # releasing worker ownership; discard obsolete queued observations.
        self.thread.join(timeout=20)
