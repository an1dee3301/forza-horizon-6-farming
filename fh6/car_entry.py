"""Recognize the locally recorded Mad Mike entry cinematic for one early Esc."""
from pathlib import Path
import cv2
import numpy as np
import forza_cycle as core


def fingerprint(frame):
    return cv2.resize(frame[180:920,240:1760],(380,185),interpolation=cv2.INTER_AREA)


class EntryCinematic:
    def __init__(self, path=core.BASE/'calibration/entry_cinematic.npz'):
        self.templates=[]
        if Path(path).exists():
            with np.load(path,allow_pickle=False) as archive:
                self.templates=list(archive['frames'])

    def matches(self, obs):
        if obs.screen != 'unknown' or not self.templates:
            return False
        frame=obs.frame
        if frame.shape[:2] != (1080,1920):
            return False
        # Entry camera has no header or dialog/footer. A loading black frame
        # still cannot pass the independently calibrated car/body comparison.
        if any(np.mean(np.max(frame[y0:y1,40:1760],axis=2)<20)<.985
               for y0,y1 in [(35,90),(1010,1050)]):
            return False
        patch=fingerprint(frame)
        return any(float(np.mean(cv2.absdiff(patch,t)))<10 for t in self.templates)
