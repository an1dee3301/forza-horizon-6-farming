"""Read the colored account-level badge when header OCR omits its digits."""
import re

import cv2


def read_level_badge(frame, reader):
    if frame is None or frame.shape[:2] != (1080, 1920):
        return None
    broad = frame[40:82,1420:1515]
    broad_mask = cv2.inRange(cv2.cvtColor(broad, cv2.COLOR_BGR2HSV),
                             (0,120,100),(179,255,255))
    contours, _ = cv2.findContours(broad_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    broad_boxes = [cv2.boundingRect(c) for c in contours]
    broad_boxes = [box for box in broad_boxes if 28 <= box[2] <= 75 and 20 <= box[3] <= 40]
    if len(broad_boxes) > 1:
        return None
    # The current teal home header joins the badge to its saturated backdrop.
    # This cell excludes the prestige star at its left and the gamertag below.
    # Color and grayscale OCR must agree before the level is accepted.
    direct = frame[60:103,1453:1518]
    direct_values = []
    if cv2.countNonZero(cv2.cvtColor(direct, cv2.COLOR_BGR2GRAY)) >= 20:
        for pixels in (direct, cv2.cvtColor(direct, cv2.COLOR_BGR2GRAY)):
            pixels = cv2.resize(pixels, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            if pixels.ndim == 2:
                pixels = cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR)
            pixels = cv2.copyMakeBorder(pixels, 20, 20, 20, 20,
                                        cv2.BORDER_CONSTANT, value=(0,0,0))
            doc = reader.read(pixels)
            values = [int(line.text) for line in doc.lines
                      if re.fullmatch(r'\d{1,4}', line.text) and 1 <= int(line.text) <= 2999]
            if len(doc.lines) == len(values) == 1:
                direct_values.append(values[0])
    if len(direct_values) == 2 and direct_values[0] == direct_values[1]:
        return direct_values[0]
    # Exclude the car rating, gamertag and credits. The white prestige star
    # is outside the saturated rectangle and must never become the level.
    x0, y0 = 1420, 40
    patch = broad
    mask = broad_mask
    boxes = broad_boxes
    padding = 3
    if not boxes:
        # Saturated green scenery can join the orange level badge into one
        # oversized component. Isolate the badge's warm hue in that case.
        mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV),
                           (0, 120, 100), (35, 255, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(c) for c in contours]
        boxes = [(x,y,w,h) for x,y,w,h in boxes if 28 <= w <= 75 and 20 <= h <= 40]
        # The rectangle already includes margins around its digits. Extra
        # outside pixels can add the adjacent prestige-cell edge to OCR.
        padding = 0
    if len(boxes) != 1:
        return None
    x,y,w,h = boxes[0]
    badge = frame[y0+y-padding:y0+y+h+padding, x0+x-padding:x0+x+w+padding]
    doc = reader.read(cv2.resize(badge, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
    values = [int(line.text) for line in doc.lines
              if re.fullmatch(r'\d{1,4}', line.text) and 1 <= int(line.text) <= 2999]
    return values[0] if len(doc.lines) == len(values) == 1 else None
