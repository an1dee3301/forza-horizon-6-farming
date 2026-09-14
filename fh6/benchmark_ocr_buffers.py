"""Compare native-buffer OCR with the old DataWriter path on saved images only.

No capture, navigation, game inputs, or live-state changes are performed.
The benchmark alternates variant order and checks exact text/box equality.
"""
import argparse
import json
import os
import time
from pathlib import Path
from statistics import median

import cv2
import numpy as np

from .ocr import Document, Text, WindowsOCR


class TimedReader(WindowsOCR):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.timing = {}

    async def _read(self, frame):
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter
        start = time.perf_counter()
        pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        writer = None
        if self.mode == 'legacy_datawriter':
            writer = DataWriter()
            writer.write_bytes(pixels.tobytes())
            buffer = writer.detach_buffer()
        else:
            buffer = memoryview(pixels)
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.BGRA8, pixels.shape[1], pixels.shape[0])
        prepared = time.perf_counter()
        try:
            result = await self.engine.recognize_async(bitmap)
            recognized = time.perf_counter()
            lines = []
            for line in result.lines:
                boxes = [word.bounding_rect for word in line.words]
                if not boxes:
                    continue
                x, y = min(b.x for b in boxes), min(b.y for b in boxes)
                right = max(b.x+b.width for b in boxes)
                bottom = max(b.y+b.height for b in boxes)
                lines.append(Text(line.text, (round(x), round(y),
                                             round(right-x), round(bottom-y))))
            extracted = time.perf_counter()
            self.timing = dict(setup_ms=(prepared-start)*1000,
                               recognize_ms=(recognized-prepared)*1000,
                               extract_ms=(extracted-recognized)*1000)
            return Document(lines)
        finally:
            bitmap.close()
            if writer is not None:
                writer.close()


def signature(document):
    return [(line.text, line.box) for line in document.lines]


def lower_process_priority():
    """Keep future offline comparisons subordinate to the active game."""
    if os.name != 'nt':
        return 'unchanged_non_windows'
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.SetPriorityClass.restype = wintypes.BOOL
    if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000):
        raise ctypes.WinError(ctypes.get_last_error())
    return 'below_normal'


def run(rounds=4):
    base = Path(__file__).resolve().parents[1]
    frames = []
    for second in (0, 6, 7, 9, 12, 34.5, 58, 59, 61):
        path = base/'video_review'/f'frame_{second:06.2f}.jpg'
        frame = cv2.imread(str(path))
        if frame is None:
            raise RuntimeError(f'Missing recorded benchmark frame: {path}')
        frames.append((path.name, frame))
    # Native-size non-contiguous views exercise the existing ROI/refine path.
    frames.extend((name+':roi', frame[310:800, 610:1310])
                  for name, frame in frames[:3])
    readers = [TimedReader('legacy_datawriter'), TimedReader('native_buffer')]
    production = WindowsOCR()
    rows, mismatches = [], []
    try:
        for reader in readers:
            reader.read(frames[0][1])
        # Confirm the measured candidate and actual production reader use the
        # same OCR result before collecting alternating latency measurements.
        for name, frame in frames:
            if signature(production.read(frame)) != signature(readers[1].read(frame)):
                mismatches.append(dict(frame=name, reason='production_vs_candidate'))
        for iteration in range(rounds):
            for index, (name, frame) in enumerate(frames):
                order = readers if (iteration+index) % 2 == 0 else readers[::-1]
                answers = {}
                for reader in order:
                    start = time.perf_counter()
                    doc = reader.read(frame)
                    row = dict(frame=name, iteration=iteration, mode=reader.mode,
                               total_ms=(time.perf_counter()-start)*1000,
                               **reader.timing)
                    rows.append(row)
                    answers[reader.mode] = signature(doc)
                if answers[readers[0].mode] != answers[readers[1].mode]:
                    mismatches.append(dict(frame=name, iteration=iteration,
                                           reason='baseline_vs_candidate'))
    finally:
        production.close()
        for reader in readers:
            reader.close()
    summaries = {}
    for mode in ('legacy_datawriter', 'native_buffer'):
        selected = [row for row in rows if row['mode'] == mode]
        summaries[mode] = {'observations': len(selected)}
        for metric in ('setup_ms', 'recognize_ms', 'extract_ms', 'total_ms'):
            values = [row[metric] for row in selected]
            summaries[mode][metric] = dict(p50=round(median(values), 3),
                                           p90=round(float(np.percentile(values, 90)), 3))
    return dict(recorded_frames=len(frames), rounds=rounds, exact_matches=not mismatches,
                mismatches=mismatches, summary=summaries,
                note='Offline OCR latency; this does not measure car-cycle speed.',
                samples=[{key:round(value, 3) if isinstance(value, float) else value
                          for key, value in row.items()} for row in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    priority = lower_process_priority()
    result = run(args.rounds)
    result['benchmark_process_priority'] = priority
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key, value in result.items() if key != 'samples'}, indent=2))
    if not result['exact_matches']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
