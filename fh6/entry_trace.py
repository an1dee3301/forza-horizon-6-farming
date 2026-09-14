"""One bounded diagnostic of the car-entry transition, using existing frames."""
import json
import time
from datetime import datetime
from pathlib import Path
import cv2


class EntryTrace:
    def __init__(self, folder):
        self.folder=Path(folder)/datetime.now().strftime('%Y%m%d_%H%M%S')
        self.started=time.perf_counter()
        self.last=-1
        self.rows=[]
        self.frames=[]

    def offer(self, obs):
        elapsed=time.perf_counter()-self.started
        if elapsed-self.last < .4 or len(self.frames)>=80:
            return
        self.last=elapsed
        ok,jpeg=cv2.imencode('.jpg',obs.frame,[cv2.IMWRITE_JPEG_QUALITY,85])
        if ok:
            self.frames.append(jpeg.tobytes())
            self.rows.append(dict(seconds=round(elapsed,3),screen=obs.screen,
                lines=[dict(text=l.text,box=l.box) for l in obs.doc.lines]))

    def finish(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        for i,blob in enumerate(self.frames):
            (self.folder/f'{i:03}.jpg').write_bytes(blob)
        (self.folder/'timeline.json').write_text(json.dumps(self.rows,indent=2),encoding='utf-8')
        return self.folder
