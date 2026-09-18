"""Read-only Wheelspin reward recognition and evidence capture.

The boxes are explicit 1920x1080 calibration candidates.  They may record raw
evidence immediately, but automated decisions remain disabled until reviewed
screens confirm the geometry.
"""
from pathlib import Path
import re

import cv2
import numpy as np

from .ocr import normalize
from .wheelspin_catalog import identify_protected, normalize_car_text


# Only the three selected centre cards.  The old regions covered each complete
# reel and mixed the selected reward with the cards above and below it.
SUPER_SLOT_BOXES = ((520, 420, 400, 245), (965, 420, 400, 245), (1410, 420, 400, 245))
REGULAR_SLOT_BOXES = ((760, 420, 400, 245),)


def slot_boxes(spin_type):
    if spin_type == "SUPER":
        return SUPER_SLOT_BOXES
    if spin_type == "REGULAR":
        return REGULAR_SLOT_BOXES
    raise ValueError("spin_type must be SUPER or REGULAR")


def _credit_value(text):
    values = re.findall(r"(?<!\d)(\d{1,3}(?:[,. ]\d{3})+|\d+)\s*CR\b", text.upper())
    return int(re.sub(r"\D", "", values[0])) if len(values) == 1 else None


def classify_reward_text(raw_text):
    raw = str(raw_text or "").strip()
    normalized = normalize_car_text(raw)
    base = dict(raw_ocr=raw, normalized_text=normalize(raw), reward_type="UNKNOWN",
                classification_confidence=0.0, year=None, manufacturer=None, model=None,
                display_name=None, forza_edition=None, wheelspin_exclusive=None,
                protected=None)
    if not normalized:
        return base
    credits = _credit_value(raw)
    if credits is not None:
        return dict(base, reward_type="CREDITS", classification_confidence=1.0,
                    credits_value=credits)
    match = identify_protected(raw)
    if match:
        car = match.car
        return dict(base, reward_type="CAR", classification_confidence=match.confidence,
                    year=car.year, manufacturer=car.manufacturer, model=car.canonical_model,
                    display_name=car.display_name, forza_edition=car.forza_edition,
                    wheelspin_exclusive=True, protected=True)
    categories = {
        "HORN": ("HORN",), "EMOTE": ("EMOTE", "DANCE"),
        "CLOTHING": ("JACKET", "SHIRT", "DRESS", "HOODIE", "TROUSERS", "SHORTS",
                     "SHOES", "BOOTS", "HAT", "CAP", "HELMET", "GLOVES", "SOCKS"),
        "COSMETIC": ("GLASSES", "MASK", "OUTFIT", "WATCH", "BACKPACK"),
    }
    for kind, words in categories.items():
        if any(f" {word} " in f" {normalized} " for word in words):
            return dict(base, reward_type=kind, classification_confidence=.90)
    years = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", normalized)
    if len(years) == 1:
        # This is recorded as a likely car, but it cannot drive sell/keep: a
        # non-catalog car still needs duplicate-dialog identification.
        tail = normalized.split(years[0], 1)[1].strip().split()
        manufacturer = tail[0] if tail else None
        model = " ".join(tail[1:]) if len(tail) > 1 else None
        confidence = .78 if manufacturer and model else .45
        return dict(base, reward_type="CAR", classification_confidence=confidence,
                    year=int(years[0]), manufacturer=manufacturer, model=model,
                    display_name=raw, forza_edition="FORZA EDITION" in normalized,
                    wheelspin_exclusive=None, protected=None)
    return dict(base, reward_type="OTHER", classification_confidence=.55)


def read_selected_card(frame, reader, box):
    """Read one selected card, with a tight numeric pass for credit cards."""
    x, y, w, h = box
    crop = frame[y:y+h, x:x+w]
    doc = reader.read(crop)
    raw = " ".join(line.text for line in doc.lines)
    item = classify_reward_text(raw)
    if item["reward_type"] in {"UNKNOWN", "OTHER"}:
        # The CR medallion can suppress Windows OCR on the full card.  The
        # amount itself occupies the right-hand centre of every selected card.
        amount = crop[45:190, 100:390]
        numeric = " ".join(line.text for line in reader.read(amount).lines)
        digits = re.findall(r"(?<!\d)(\d{1,3}(?:[,. ]\d{3})+)(?!\d)", numeric)
        if len(digits) == 1:
            value = int(re.sub(r"\D", "", digits[0]))
            item = dict(item, raw_ocr=numeric, normalized_text=normalize(numeric),
                        reward_type="CREDITS", classification_confidence=1.0,
                        credits_value=value)
        else:
            # Small green/blue 5,000 cards are the recurring Windows OCR
            # miss.  Use several high-contrast numeric views and accept only
            # a majority value.  The comma-shaped thousands pattern excludes
            # the round CR medallion, which OCR sometimes reads as zero.
            gray = cv2.cvtColor(crop[35:200, 50:395], cv2.COLOR_BGR2GRAY)
            votes = []
            for scale, threshold in ((1.5, 180), (1.5, 210),
                                     (2.0, 100), (2.0, 140)):
                enlarged = cv2.resize(gray, None, fx=scale, fy=scale,
                                      interpolation=cv2.INTER_CUBIC)
                _, binary = cv2.threshold(enlarged, threshold, 255,
                                          cv2.THRESH_BINARY)
                variant = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                variant_text = " ".join(line.text for line in reader.read(variant).lines)
                formatted = re.findall(r"(?<!\d)(\d{1,3}(?:[,.]\d{3})+)(?!\d)",
                                       variant_text)
                if len(formatted) == 1:
                    votes.append((int(re.sub(r"\D", "", formatted[0])), variant_text))
            if votes:
                from collections import Counter
                value, count = Counter(value for value, _ in votes).most_common(1)[0]
                if count >= 2:
                    evidence = next(text for candidate, text in votes if candidate == value)
                    item = dict(item, raw_ocr=evidence,
                                normalized_text=normalize(evidence),
                                reward_type="CREDITS", classification_confidence=.99,
                                credits_value=value)
    return crop, item


def stable_rewards(observations, slot_count):
    if len(observations) < 3 or any(len(row) != slot_count for row in observations[-3:]):
        raise RuntimeError("Reward screen is not stable across three complete observations")
    signatures = [tuple(item.get("normalized_text", "") for item in row) for row in observations[-3:]]
    if not signatures[0] == signatures[1] == signatures[2] or any(not value for value in signatures[0]):
        raise RuntimeError("Reward screen is not stable across three complete observations")
    return observations[-1]


def card_colour(crop):
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    height, width = hsv.shape[:2]
    border = np.zeros((height, width), dtype=bool)
    border[:25, :] = True
    border[-45:, :] = True
    border[:, :20] = True
    border[:, -20:] = True
    saturated = border & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 80)
    hues = hsv[:, :, 0][saturated]
    if hues.size < 100:
        return "NEUTRAL"
    # The colored card frame is a much better rarity signal than the median
    # of the whole crop, which is dominated by its white label and car art.
    h = int(np.bincount(hues, minlength=180).argmax())
    if 8 <= h < 25:
        return "ORANGE"
    if 125 <= h < 170:
        return "PURPLE"
    if 90 <= h < 125:
        return "BLUE"
    if 35 <= h < 90:
        return "GREEN"
    return "OTHER"


def _atomic_png(path, frame):
    ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError(f"Could not encode reward evidence {path}")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(path)


def capture_reward_observation(frame, reader, folder, spin_number, spin_type):
    if frame.shape[:2] != (1080, 1920):
        raise RuntimeError("Wheelspin Lab requires the verified 1920 x 1080 layout")
    root = Path(folder) / f"spin_{int(spin_number):06d}"
    full = root / "full.png"
    _atomic_png(full, frame)
    rewards = []
    for index, (x, y, w, h) in enumerate(slot_boxes(spin_type), 1):
        crop, item = read_selected_card(frame, reader, (x, y, w, h))
        crop = crop.copy()
        path = root / f"slot_{index}.png"
        _atomic_png(path, crop)
        item.update(slot_index=index, card_color=card_colour(crop),
                    full_screen_path=str(full.resolve()), slot_crop_path=str(path.resolve()))
        rewards.append(item)
    return str(full.resolve()), rewards


def read_reward_observation(frame, reader, spin_type):
    """Read slot ROIs without persistence; used only to prove three-frame stability."""
    if frame.shape[:2] != (1080, 1920):
        raise RuntimeError("Wheelspin Lab requires the verified 1920 x 1080 layout")
    rewards = []
    for index, (x, y, w, h) in enumerate(slot_boxes(spin_type), 1):
        crop, item = read_selected_card(frame, reader, (x, y, w, h))
        item.update(slot_index=index, card_color=card_colour(crop))
        rewards.append(item)
    return rewards
