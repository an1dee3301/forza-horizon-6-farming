"""Local Windows OCR. Images never leave this computer."""
import asyncio
import re
from dataclasses import dataclass
from functools import lru_cache

import cv2


@lru_cache(maxsize=2048)
def normalize(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.casefold()))


@dataclass(frozen=True)
class Text:
    text: str
    box: tuple

    @property
    def center(self):
        x, y, w, h = self.box
        return round(x + w / 2), round(y + h / 2)


class Document:
    def __init__(self, lines):
        self.lines = lines

    def find(self, label, region=None, contains=False):
        wanted = normalize(label)
        matches = []
        for line in self.lines:
            value = normalize(line.text)
            if not (wanted == value or (contains and f' {wanted} ' in f' {value} ')):
                continue
            if region:
                x, y = line.center
                rx, ry, rw, rh = region
                if not (rx <= x < rx+rw and ry <= y < ry+rh):
                    continue
            matches.append(line)
        return matches

    def has(self, label, region=None, contains=False):
        return bool(self.find(label, region, contains))

    def unique(self, label, region=None, contains=False):
        matches = self.find(label, region, contains)
        if len(matches) != 1:
            raise RuntimeError(f'Expected one visible "{label}" label; found {len(matches)}')
        return matches[0]


class WindowsOCR:
    def __init__(self):
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        self.engine = OcrEngine.try_create_from_language(Language('en-US'))
        if self.engine is None:
            raise RuntimeError('Windows English OCR is unavailable. Install English language OCR in Windows Settings.')
        self.loop = asyncio.new_event_loop()

    async def _read(self, frame):
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        # PyWinRT 3.2+ accepts the Python buffer protocol for IBuffer. Keep the
        # full-resolution BGRA pixels but avoid a bytes and DataWriter copy.
        # create_copy_from_buffer owns its copy before recognition starts.
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            memoryview(pixels), BitmapPixelFormat.BGRA8,
            pixels.shape[1], pixels.shape[0])
        try:
            result = await self.engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                boxes = [w.bounding_rect for w in line.words]
                if not boxes:
                    continue
                x, y = min(b.x for b in boxes), min(b.y for b in boxes)
                right = max(b.x+b.width for b in boxes)
                bottom = max(b.y+b.height for b in boxes)
                lines.append(Text(line.text, (round(x), round(y), round(right-x), round(bottom-y))))
            return Document(lines)
        finally:
            bitmap.close()

    def read(self, frame):
        return self.loop.run_until_complete(asyncio.wait_for(self._read(frame), timeout=5))

    def read_regions(self, frame, boxes):
        """OCR disjoint UI regions and restore their full-screen coordinates."""
        lines = []
        for x, y, w, h in boxes:
            local = self.read(frame[y:y+h, x:x+w])
            lines.extend(Text(line.text, (line.box[0]+x, line.box[1]+y,
                                          *line.box[2:]))
                         for line in local.lines)
        return Document(lines)

    def refine_region(self, frame, document, box):
        x, y, w, h = box
        local = self.read(frame[y:y+h, x:x+w])
        retained = [line for line in document.lines if not
                    (x <= line.center[0] < x+w and y <= line.center[1] < y+h)]
        retained.extend(Text(line.text, (line.box[0]+x, line.box[1]+y, *line.box[2:]))
                        for line in local.lines)
        return Document(retained)

    def close(self):
        self.loop.close()
