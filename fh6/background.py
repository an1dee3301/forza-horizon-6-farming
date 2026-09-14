"""One ordered, bounded stream for non-authoritative diagnostics and UI work."""
import queue
import threading


class BackgroundStream:
    def __init__(self, capacity=4096):
        self.queue=queue.Queue(capacity)
        self.dropped=0
        self.errors=0
        self.closed=False
        self.thread=threading.Thread(target=self._work,name='FH6 diagnostics',daemon=True)
        self.thread.start()

    def submit(self, action, *args):
        if self.closed: return False
        try:
            self.queue.put_nowait((action,args))
            return True
        except queue.Full:
            self.dropped+=1
            return False

    def _work(self):
        while True:
            item=self.queue.get()
            try:
                if item is None: return
                action,args=item
                action(*args)
            except Exception:
                self.errors+=1
            finally:
                self.queue.task_done()

    def close(self):
        # Only called after inputs stop; drain in order before owner exits.
        self.closed=True
        self.queue.join()
        self.queue.put(None)
        self.thread.join(timeout=5)
