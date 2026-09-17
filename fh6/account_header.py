"""Calibrated account strip shared by background OCR and report evidence."""
import io
import re
from functools import lru_cache
from pathlib import Path
from datetime import datetime

ACCOUNT_BOX = (1405, 35, 490, 60)  # x, y, width, height at 1920x1080
_DIGIT_TEMPLATES = Path(__file__).resolve().parent.parent/'recognition'/'credit_digits'


def _normalise_credit_digit(pixels):
    """Turn one masked FH6 credit glyph into the template's fixed canvas."""
    import cv2
    import numpy as np
    ys, xs = np.where(pixels > 0)
    if not len(xs):
        return None
    glyph = pixels[ys.min():ys.max()+1, xs.min():xs.max()+1]
    scale = min(18/glyph.shape[1], 24/glyph.shape[0])
    glyph = cv2.resize(glyph, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((28, 22), dtype=np.uint8)
    y, x = (28-glyph.shape[0])//2, (22-glyph.shape[1])//2
    canvas[y:y+glyph.shape[0], x:x+glyph.shape[1]] = glyph
    return canvas


@lru_cache(maxsize=1)
def _credit_templates():
    """Load glyphs sampled from native FH6 account headers."""
    import cv2
    import json
    try:
        manifest = json.loads((_DIGIT_TEMPLATES/'manifest.json').read_text(encoding='utf-8'))
        rows = []
        for item in manifest['templates']:
            glyph = cv2.imread(str(_DIGIT_TEMPLATES/item['file']), cv2.IMREAD_GRAYSCALE)
            if glyph is None or glyph.shape != (28, 22):
                return ()
            rows.append((str(item['digit']), glyph))
        return tuple(rows)
    except (OSError, KeyError, TypeError, ValueError):
        return ()


def _template_yellow_credits(frame):
    """Read the fixed FH6 account balance without relying on Windows OCR.

    The CR medallion anchors the row, the two comma components establish the
    character cells, and every digit must match a native game-font template.
    AccountObserver still requires the same result on two fresh frames before
    the value can authorize a purchase.
    """
    import cv2
    import numpy as np
    if frame is None or frame.shape[:2] != (1080, 1920):
        return None
    templates = _credit_templates()
    if not templates:
        return None
    header = cv2.inRange(cv2.cvtColor(frame[:220], cv2.COLOR_BGR2HSV),
                         (18, 100, 100), (45, 255, 255))
    _, _, stats, _ = cv2.connectedComponentsWithStats(header)
    anchors = []
    for x, y, w, h, area in stats[1:]:
        if not (x > 1300 and 15 <= w <= 30 and 18 <= h <= 30 and 180 <= area <= 360):
            continue
        right = cv2.countNonZero(header[max(0, y-2):min(220, y+h+8),
                                         x+w+5:min(1920, x+w+200)])
        if right >= 300:
            anchors.append((right, x, y, w, h))
    if len(anchors) != 1:
        return None
    _, x, y, w, h = anchors[0]
    row = header[max(0, y-2):min(220, y+h+8), x+w+5:min(1920, x+w+200)]
    _, _, parts, _ = cv2.connectedComponentsWithStats(row)
    commas = sorted((int(px), int(py), int(pw), int(ph))
        for px, py, pw, ph, area in parts[1:]
        if py >= row.shape[0]*.48 and 2 <= pw <= 6 and 3 <= ph <= 9 and area >= 5)
    if len(commas) != 2:
        return None
    upper = np.where((row[:round(row.shape[0]*.70)] > 0).any(axis=0))[0]
    if not len(upper):
        return None
    start, end = int(upper.min()), int(upper.max())+1
    c1, c2 = commas
    last_start = c2[0]+c2[2]+1
    pitch = (end-last_start)/3
    first_count = round((c1[0]-start)/pitch) if pitch > 0 else 0
    if first_count not in (1, 2, 3):
        return None
    groups = ((start, c1[0], first_count),
              (c1[0]+c1[2]+1, c2[0], 3),
              (last_start, end, 3))
    glyphs = []
    for left, right, count in groups:
        bounds = np.linspace(left, right, count+1).round().astype(int)
        for a, b in zip(bounds, bounds[1:]):
            glyph = _normalise_credit_digit(row[:, a:b])
            if glyph is None:
                return None
            glyphs.append(glyph)
    digits = []
    for glyph in glyphs:
        by_digit = {}
        total = np.count_nonzero(glyph)
        for digit, template in templates:
            denominator = total+np.count_nonzero(template)
            score = (2*np.logical_and(glyph > 0, template > 0).sum()/denominator
                     if denominator else 0)
            by_digit[digit] = max(score, by_digit.get(digit, 0))
        ranked = sorted(by_digit.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) < 2 or ranked[0][1] < .72 or ranked[0][1]-ranked[1][1] < .035:
            return None
        digits.append(ranked[0][0])
    value = int(''.join(digits))
    return f'{value:,}'


def compact_capture_box(doc, tag):
    """Keep account pixels when the first OCR pass misses yellow credits."""
    if not isinstance(tag, str) or not tag:
        return None
    tags = [line for line in doc.lines if tag.casefold() in line.text.casefold()
            and 1300 <= line.box[0] <= 1650 and 90 <= line.box[1] <= 135]
    return (1300, 40, 440, 155) if len(tags) == 1 else None


def refine_compact_header(frame, doc, tag, reader):
    box = compact_capture_box(doc, tag)
    if box is None:
        return None
    import cv2
    from .ocr import Document, Text
    x, y, w, h = box
    enlarged = reader.read(cv2.resize(frame[y:y+h, x:x+w], None, fx=3, fy=3,
                                      interpolation=cv2.INTER_CUBIC))
    refined = Document([Text(line.text, (round(line.box[0]/3)+x,
        round(line.box[1]/3)+y, round(line.box[2]/3), round(line.box[3]/3)))
        for line in enlarged.lines])
    card = compact_header(refined, tag)
    if card is not None:
        return card
    # Yellow digits on teal disappear in the full-card OCR pass. Read only
    # their calibrated row in grayscale, still requiring the account name.
    if compact_capture_box(refined, tag) is None:
        return None
    # The compact home header uses yellow digits on teal. Windows OCR reads
    # the anti-aliased color crop and isolated mask differently; accept only
    # when at least two independent preprocessings agree.
    # Include the first credit digit.  The CR badge ends around x=1444 on the
    # compact Cars menu while the amount can begin at x=1450; the old x=1460
    # crop intermittently turned 15,258,220 into 5,258,220 or no OCR result.
    patch = frame[125:166,1445:1665]
    hsv = cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    masks = [cv2.inRange(hsv, low, high) for low, high in (
        ((15,70,90),(55,255,255)),
        ((20,120,140),(42,255,255)),
        ((15,40,120),(60,255,255)),
    )]
    if max(cv2.countNonZero(mask) for mask in masks) < 20:
        return None
    readings = []
    for pixels in masks:
        scale, border, background = 2, 40, 0
        pixels = cv2.resize(pixels,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        if pixels.ndim == 2:
            pixels = cv2.cvtColor(pixels,cv2.COLOR_GRAY2BGR)
        pixels = cv2.copyMakeBorder(pixels,border,border,border,border,
                                    cv2.BORDER_CONSTANT,value=(background,)*3)
        result = reader.read(pixels)
        candidate = ' '.join(line.text for line in result.lines).strip()
        if re.fullmatch(r'(?:0|[1-9]\d{0,2}(?:[ ,]\d{3})+)', candidate):
            readings.append(int(re.sub(r'\D','',candidate)))
    # On the teal My Horizon header the stricter saturation masks sometimes
    # erase the thin comma strokes.  Re-read the broad yellow mask at two
    # different scales and still require agreement.  This preserves the
    # two-observation safety rule while avoiding a permanent retry loop when
    # only one color threshold is legible.
    if not any(readings.count(value) >= 2 for value in set(readings)):
        for scale in (3, 4):
            pixels = cv2.resize(masks[0],None,fx=scale,fy=scale,
                                interpolation=cv2.INTER_CUBIC)
            pixels = cv2.cvtColor(pixels,cv2.COLOR_GRAY2BGR)
            pixels = cv2.copyMakeBorder(pixels,border,border,border,border,
                                        cv2.BORDER_CONSTANT,value=(background,)*3)
            result = reader.read(pixels)
            candidate = ' '.join(line.text for line in result.lines).strip()
            if re.fullmatch(r'(?:0|[1-9]\d{0,2}(?:[ ,]\d{3})+)', candidate):
                readings.append(int(re.sub(r'\D','',candidate)))
    if not any(readings.count(value) >= 2 for value in set(readings)):
        # Cubic ringing can erase the compact nine-digit balance. A linear
        # enlargement preserves its strokes; agreement and fresh-frame checks
        # remain mandatory before the balance can authorize purchases.
        for scale in (3, 4):
            pixels = cv2.resize(masks[0], None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_LINEAR)
            pixels = cv2.copyMakeBorder(cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR),
                40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            candidate = ' '.join(line.text for line in reader.read(pixels).lines).strip()
            if re.fullmatch(r'(?:0|[1-9]\d{0,2}(?:[ ,]\d{3})+)', candidate):
                readings.append(int(re.sub(r'\D', '', candidate)))
    agreed = [value for value in set(readings) if readings.count(value) >= 2]
    if len(agreed) != 1:
        return None
    text = f'{agreed[0]:,}'
    card = compact_header(Document(list(refined.lines)+[Text(text,(1465,135,190,25))]),tag)
    if card is not None and card.get('level') is None:
        from .account_badge import read_level_badge
        card['level'] = read_level_badge(frame, reader)
    return card


def read_yellow_credits(frame, reader):
    import cv2
    patch=frame[35:95,1710:1895]
    mask=cv2.inRange(cv2.cvtColor(patch,cv2.COLOR_BGR2HSV),(18,100,100),(45,255,255))
    doc=reader.read(cv2.cvtColor(cv2.resize(mask,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC),cv2.COLOR_GRAY2BGR))
    if not isinstance(doc.lines,list):return None
    values=re.findall(r'(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)',' '.join(l.text for l in doc.lines))
    if len(values)==1:
        return values[0]
    # Yellow-on-dark nine-digit balances can disappear in HSV OCR. Require
    # agreement at two scales of a separate grayscale contrast transform.
    gray=cv2.cvtColor(frame[43:79,1740:1880],cv2.COLOR_BGR2GRAY)
    contrast=cv2.threshold(gray,150,255,cv2.THRESH_BINARY_INV)[1]
    readings=[]
    for scale in (2,4):
        text=' '.join(l.text for l in reader.read(cv2.cvtColor(
            cv2.resize(contrast,None,fx=scale,fy=scale),cv2.COLOR_GRAY2BGR)).lines).strip()
        if re.fullmatch(r'\d{1,3}(?:,\d{3})+',text):
            readings.append(text)
    if len(readings)==2 and readings[0]==readings[1]:
        return readings[0]
    return _template_yellow_credits(frame)


def compact_header(doc, tag):
    """Locate the stacked account card by identity + credits, not scenery."""
    if not tag:return None
    tags=[l for l in doc.lines if tag.casefold() in l.text.casefold()
          and 0<=l.box[0]<1920 and 0<=l.box[1]<220]
    if len(tags)!=1:return None
    identity=tags[0];x,y,w,h=identity.box
    credits=[l for l in doc.lines if abs(l.box[0]-x)<h*3 and
             y+h*.5<=l.box[1]<=y+h*3 and re.search(r'\d{1,3}(?:,\d{3})+',l.text)]
    if len(credits)!=1:return None
    values=re.findall(r'(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)',credits[0].text)
    if len(values)!=1:return None
    levels=[l for l in doc.lines if x-h<=l.box[0]<=x+h*5 and y-h*2<=l.box[1]<y
            and re.fullmatch(r'\d{2,4}',l.text)]
    left=max(0,x-h*6);top=max(0,y-h*2.5)
    right=min(1920,max(x+w,credits[0].box[0]+credits[0].box[2])+h*2)
    bottom=min(1080,credits[0].box[1]+credits[0].box[3]+h)
    box=tuple(round(v) for v in (left,top,right-left,bottom-top))
    if box[2]>800 or box[3]>240:return None
    return dict(box=box,credits=int(values[0].replace(',','')),
                level=int(levels[0].text) if len(levels)==1 else None,tag=tag)


def cache_strip(frame, doc, account, observed_at, root, layout='horizontal'):
    """Cache only a twice-read identified account, keeping capture time."""
    from pathlib import Path
    import cv2, hashlib
    from .reporting import read_json, write_json
    tag=account.get('gamertag')
    if not tag or not account.get('credits_observed_at')==observed_at:return
    if layout=='compact':
        card=compact_header(doc,tag)
        if not card or card['credits']!=account.get('credits'):return
        x,y,w,h=card['box']
    else:x,y,w,h=ACCOUNT_BOX
    root=Path(root);goal=read_json(root/'goal.json')
    if not goal.get('id'):return
    path=root/'reports'/'account_strip.json'
    previous=read_json(path)
    if previous.get('goal_id')==goal['id'] and previous.get('gamertag')==tag:
        try:
            if datetime.fromisoformat(observed_at).timestamp()-datetime.fromisoformat(previous['observed_at']).timestamp()<5:return
        except (ValueError,KeyError):pass
    ok,encoded=cv2.imencode('.png',frame[y:y+h,x:x+w])
    if not ok:return
    blob=encoded.tobytes();path.parent.mkdir(parents=True,exist_ok=True)
    image=path.with_suffix('.png');temporary=image.with_suffix('.tmp')
    temporary.write_bytes(blob);temporary.replace(image)
    write_json(path,dict(goal_id=goal['id'],gamertag=tag,observed_at=observed_at,
                         layout=layout,sha256=hashlib.sha256(blob).hexdigest()))


def latest_strip(game_image, data, root=None):
    from pathlib import Path
    import hashlib
    from .reporting import RUNS, read_json
    candidates=[]
    capture=data.get('game_capture') or {}
    # New game captures may occur during a transition. Their screen label is
    # not account proof; prefer the separately verified account cache.
    horizontal=not capture.get('verified_game')
    garage=report_strip(game_image) if horizontal else None
    if garage:candidates.append(garage)
    path=Path(root or RUNS)/'reports'/'account_strip.json';meta=read_json(path)
    if (meta.get('goal_id')==data.get('goal_id') and data.get('goal_id') and
            meta.get('gamertag')==(data.get('account') or {}).get('gamertag') and
            meta.get('layout') in {'horizontal','compact'}):
        try:
            blob=path.with_suffix('.png').read_bytes()
            if hashlib.sha256(blob).hexdigest()==meta.get('sha256'):
                candidates.append((blob,meta['observed_at']))
        except (OSError,KeyError):pass
    valid=[]
    for blob,stamp in candidates:
        try:valid.append((datetime.fromisoformat(stamp).timestamp(),blob,stamp))
        except (ValueError,TypeError):continue
    if not valid:return garage  # Legacy callers may provide a display-only timestamp.
    _,blob,stamp=max(valid,key=lambda item:item[0])
    return blob,stamp


def report_strip(game_image):
    if not game_image:
        return None
    from PIL import Image
    with Image.open(io.BytesIO(game_image[0])) as frame:
        if frame.size != (1920, 1080):
            return None
        x, y, w, h = ACCOUNT_BOX
        strip = frame.crop((x, y, x+w, y+h))
        buffer = io.BytesIO()
        strip.save(buffer, format='PNG')
        return buffer.getvalue(), game_image[1]


def read_prestige(frame, reader):
    """Only the digit below the prestige star; never the adjacent level."""
    import cv2
    import re
    if frame is None or frame.shape[:2] != (1080, 1920):
        return None
    patch = frame[61:79, 1435:1452]
    # Windows OCR drops isolated characters. Repeating only these pixels gives
    # it a text row; this is ONE reading, not four independent confirmations.
    patch = cv2.copyMakeBorder(patch, 5, 5, 6, 6, cv2.BORDER_CONSTANT, value=(0,0,0))
    row = cv2.resize(cv2.hconcat([patch]*4), None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    doc = reader.read(row)
    if not isinstance(doc.lines, list):
        return None
    digits = ''.join(line.text.replace(' ', '') for line in doc.lines)
    if re.fullmatch(r'([0-9])\1{3}', digits):
        return int(digits[0])
    # Mixed/partial numeric readings are ambiguous, not missing evidence.
    if re.search(r'\d', digits):
        return None
    return _read_prestige_component(frame, reader)


def _read_prestige_component(frame, reader):
    """Recover a tiny white digit when level-badge width shifts its position.

    The crop ends before the level's text. A thin badge edge can fall inside;
    it is not digit-shaped. Never infer prestige from the account level.
    """
    import cv2
    patch = frame[62:77, 1438:1457]
    mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV),
                       (0, 0, 140), (179, 80, 255))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates = [(label, stat) for label, stat in enumerate(stats[1:], 1)
                  if 3 <= stat[2] <= 10 and 7 <= stat[3] <= 12
                  and stat[4] >= 10]
    if len(candidates) != 1:
        return None
    label, (x, y, w, h, _) = candidates[0]
    # The binary mask only locates the digit. Preserve its anti-aliased
    # outline for OCR: a one-pixel threshold change can turn a tiny 5 into S.
    glyph = cv2.cvtColor(patch[max(0,y-1):y+h+1, max(0,x-1):x+w+1],
                         cv2.COLOR_BGR2GRAY)
    cell = cv2.copyMakeBorder(glyph, 2, 2, 1, 1, cv2.BORDER_CONSTANT, value=0)
    row = cv2.copyMakeBorder(cv2.hconcat([cell]*4), 4, 4, 4, 4,
                             cv2.BORDER_CONSTANT, value=0)
    readings = []
    for scale in (4, 6):
        image = cv2.resize(row, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        doc = reader.read(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
        if not isinstance(doc.lines, list):
            return None
        digits = ''.join(line.text.replace(' ', '') for line in doc.lines)
        if not re.fullmatch(r'([0-9])\1{3}', digits):
            return None
        readings.append(int(digits[0]))
    # Both variants are still ONE frame observation. AccountObserver retains
    # its separate two-observation agreement before publishing this value.
    return readings[0] if readings[0] == readings[1] else None
