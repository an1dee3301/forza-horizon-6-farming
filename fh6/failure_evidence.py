"""Freeze failure evidence before asynchronous writing; never touch game APIs."""
import copy
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np


def _notify(emit, kind, message):
    try:
        emit(kind, message)
    except Exception:
        pass  # UI/log callbacks cannot replace the original game error.


class FailureEvidence:
    """At most one full frame may wait in the shared diagnostic stream."""
    def __init__(self):
        self.pending = threading.Lock()

    def submit(self, path, report, *, observation=None, frame=None, stream=None,
               emit=lambda *args: None):
        if not self.pending.acquire(blocking=False):
            _notify(emit, 'log', 'Failure evidence busy; original error retained in the log.')
            return False
        try:
            frozen = copy.deepcopy(report)
            if observation is not None:
                frame = observation.frame
                lines = [dict(text=line.text, box=list(line.box)) for line in observation.doc.lines]
                frozen['last_screen'] = observation.screen
                frozen['last_observation_text'] = [line['text'] for line in lines]
                frozen['observation_lines'] = lines
                frozen['recognition'] = copy.deepcopy(getattr(observation, 'result', {}))
                captured = getattr(observation, 'captured_monotonic', None)
                frozen['observation_age_seconds'] = (max(0, time.monotonic()-captured)
                    if isinstance(captured, (int, float)) else None)
                frozen['focus_generation'] = getattr(observation, 'focus_generation', None)
            pixels = np.array(frame, copy=True) if frame is not None else None
            if pixels is None:
                frozen.setdefault('diagnostic_error', 'No observation image was available.')
            if stream is not None:
                if not stream.submit(self._write, Path(path), frozen, pixels, emit):
                    self.pending.release()
                    _notify(emit, 'log', 'Failure evidence queue full; original error retained in the log.')
                    return False
            else:
                self._write(Path(path), frozen, pixels, emit)
            return True
        except Exception as exc:
            self.pending.release()
            _notify(emit, 'log', f'Could not freeze failure evidence: {exc}')
            return False

    def _write(self, path, report, pixels, emit):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if pixels is not None:
                try:
                    if not cv2.imwrite(str(path), pixels):
                        raise RuntimeError('Could not write error screenshot')
                    _notify(emit, 'error_image', str(path))
                except Exception as exc:
                    report['diagnostic_error'] = str(exc)
            path.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        except Exception as exc:
            _notify(emit, 'log', f'Could not save error details: {exc}')
        finally:
            self.pending.release()
