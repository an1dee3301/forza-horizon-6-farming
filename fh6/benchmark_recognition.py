"""Read-only timing on recorded game frames; sends no game inputs."""
import json
import time
from statistics import median
import cv2
import forza_cycle as core
from .ocr import WindowsOCR, Document, Text
from .navigation import menu_name


def main():
    reader, recognizer = WindowsOCR(), core.Recognizer()
    rows=[]
    try:
        for second in (0,6,7,9,12,34.5,58,59,61):
            frame=cv2.imread(str(core.BASE/'video_review'/f'frame_{second:06.2f}.jpg'))
            start=time.perf_counter()
            result=recognizer.inspect(frame)
            recognition=time.perf_counter()-start
            variants={}
            for scale in (1,.75,.5):
                image=frame if scale==1 else cv2.resize(frame,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
                start=time.perf_counter()
                doc=reader.read(image)
                elapsed=time.perf_counter()-start
                doc=Document([Text(line.text,tuple(round(v/scale) for v in line.box)) for line in doc.lines])
                variants[str(scale)]=dict(ms=round(elapsed*1000,2),screen=menu_name(doc,result),lines=len(doc.lines))
            rows.append(dict(second=second,recognizer_ms=round(recognition*1000,2),variants=variants))
    finally:
        reader.close()
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    main()
