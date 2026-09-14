"""Offline native-resolution OCR experiments; never imported by game navigation.

Run with ``python -m fh6.benchmark_ui_regions --repeats 3 --output PATH``.
This reads existing recordings only, sends no inputs, and never captures the
desktop. Crop variants are research candidates, not safe global guard readers.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
import time

import cv2
import numpy as np

import forza_cycle as core
from .cloud_sync import sync_state
from .navigation import menu_name
from .ocr import Document, Text, WindowsOCR, normalize


# Native pixels, with output boxes mapped back to the original frame. The
# deliberately narrow home variant quantifies how much a known-menu shortcut
# loses when a dialog appears. It MUST NOT replace the global observation.
PLANS = {
    'edge_trim': ((35, 25, 1850, 1020),),
    'home_only': ((45, 125, 490, 830), (535, 125, 600, 90)),
    'home_and_dialog': ((45, 125, 1300, 830), (45, 25, 1840, 85),
                        (45, 970, 1840, 85)),
    'full_width_bands': ((0, 0, 1920, 270), (0, 270, 1920, 700),
                         (0, 970, 1920, 110)),
}
DANGER = ('insufficient credits', 'not enough credits', 'cannot afford',
          'not enough skill points', 'garage is full', 'connection lost',
          'disconnected', 'remove car', 'delete car', 'video card crash',
          'terminated unexpectedly', 'fhc11')
ACTIONS = ('Collection Journal', 'Settings', 'My Cars', 'Designs & Paints',
           'Upgrades & Tuning', 'Car Mastery', 'Master Explorer', 'Car Collection',
           'Manufacturers', 'Mazda', 'Recently Added', 'All Cars', 'Get In Car',
           'Buy', 'Cancel', 'Like', 'Dislike', 'Confirm', 'Share Code', 'Enter',
           'Continue', 'Back', 'Yes', 'No', 'Remove Car From Garage')
DEFAULT_SECONDS = (0, 6, 7, 9, 12, 20, 22.4, 23, 30, 34.5, 35.5, 42,
                   58, 59, 61, 66.5, 93, 96)
DEFAULT_FAILURES = (
    'pipeline_20260912_154331_304132',  # Missing My Cars OCR during entry.
    'pipeline_20260912_142748_695436',  # Rating dialog.
    'pipeline_20260910_073421_476568',  # Search form + IME-like overlay.
    'pipeline_20260910_221618_221703',  # Disconnect warning + crash dialog.
    'pipeline_20260912_135649_809440',  # Crash on challenge browser.
    'pipeline_20260912_041950_858131',  # Crash on unknown background.
)


def validate_boxes(frame, boxes):
    height, width = frame.shape[:2]
    for x, y, w, h in boxes:
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > width or y+h > height:
            raise ValueError('Crop must lie completely inside its source frame')


def pack_regions(frame, boxes, gap=24):
    """Pack crops vertically without resizing and retain a reversible mapping."""
    validate_boxes(frame, boxes)
    width = max(w for _, _, w, _ in boxes) + 2*gap
    height = sum(h for _, _, _, h in boxes) + (len(boxes)+1)*gap
    packed = np.zeros((height, width, 3), dtype=frame.dtype)
    placements, dy = [], gap
    for box in boxes:
        x, y, w, h = box
        packed[dy:dy+h, gap:gap+w] = frame[y:y+h, x:x+w]
        placements.append((box, (gap, dy, w, h)))
        dy += h+gap
    return packed, placements


def restore_document(document, placements):
    """Reject OCR lines crossing crop boundaries instead of inventing positions."""
    lines, rejected = [], 0
    for line in document.lines:
        lx, ly, lw, lh = line.box
        fits = [(source, target) for source, target in placements
                if target[0] <= lx and target[1] <= ly and
                lx+lw <= target[0]+target[2] and ly+lh <= target[1]+target[3]]
        if len(fits) != 1:
            rejected += 1
            continue
        (sx, sy, _, _), (dx, dy, _, _) = fits[0]
        lines.append(Text(line.text, (sx+lx-dx, sy+ly-dy, lw, lh)))
    return Document(lines), rejected


def read_variant(reader, frame, variant):
    if variant == 'full':
        return reader.read(frame), 0, frame.shape[0]*frame.shape[1]
    if variant == 'home_multi':
        lines, pixels = [], 0
        for x, y, w, h in PLANS['home_only']:
            local = reader.read(frame[y:y+h, x:x+w])
            pixels += w*h
            lines.extend(Text(line.text, (x+line.box[0], y+line.box[1], *line.box[2:]))
                         for line in local.lines)
        return Document(lines), 0, pixels
    if variant == 'edge_trim':
        x, y, w, h = PLANS[variant][0]
        local = reader.read(frame[y:y+h, x:x+w])
        return Document([Text(line.text, (x+line.box[0], y+line.box[1], *line.box[2:]))
                         for line in local.lines]), 0, w*h
    image, placements = pack_regions(frame, PLANS[variant])
    document, rejected = restore_document(reader.read(image), placements)
    return document, rejected, image.shape[0]*image.shape[1]


def signatures(document):
    text = normalize(' '.join(line.text for line in document.lines))
    return {
        'actions': sorted(label for label in ACTIONS if document.has(label)),
        'danger': [phrase for phrase in DANGER if phrase in text],
        'sync': sync_state(document),
    }


def compare_documents(baseline, candidate):
    original, proposed = signatures(baseline), signatures(candidate)
    words_before = Counter(normalize(' '.join(line.text for line in baseline.lines)).split())
    words_after = Counter(normalize(' '.join(line.text for line in candidate.lines)).split())
    return {
        'lost_actions': sorted(set(original['actions'])-set(proposed['actions'])),
        'added_actions': sorted(set(proposed['actions'])-set(original['actions'])),
        'lost_danger': sorted(set(original['danger'])-set(proposed['danger'])),
        'sync_agreement': original['sync'] == proposed['sync'],
        'baseline_sync': original['sync'],
        'baseline_danger': original['danger'],
        'baseline_action_count': len(original['actions']),
        'token_retention': (sum((words_before & words_after).values()) /
                            max(1, sum(words_before.values()))),
    }


def benchmark(paths, repeats=3):
    if repeats < 1:
        raise ValueError('At least one measured repetition is required')
    reader, recognizer = WindowsOCR(), core.Recognizer()
    rows, skipped = [], []
    variants = ('full', 'edge_trim', 'home_only', 'home_multi',
                'home_and_dialog', 'full_width_bands')
    try:
        for path in paths:
            frame = cv2.imread(str(path))
            if frame is None or frame.shape[:2] != (1080, 1920):
                skipped.append(str(path))
                continue
            result = recognizer.inspect(frame)
            baseline = reader.read(frame)  # Separate warm-up and reference.
            base_screen = menu_name(baseline, result)
            samples = {name: [] for name in variants}
            documents = {}
            for repeat in range(repeats):
                # Rotate order so CPU contention and warm caches don't always
                # favour a particular variant. OCR operations remain serial.
                order = variants[repeat % len(variants):] + variants[:repeat % len(variants)]
                for name in order:
                    started = time.perf_counter()
                    document, rejected, pixels = read_variant(reader, frame, name)
                    elapsed = (time.perf_counter()-started)*1000
                    samples[name].append(elapsed)
                    documents[name] = (document, rejected, pixels)
            row = {'path': str(path.relative_to(core.BASE)), 'screen': base_screen,
                   'calibrated_screen': result['screen'], 'variants': {}}
            for name, (document, rejected, pixels) in documents.items():
                comparison = compare_documents(baseline, document)
                row['variants'][name] = {
                    'ocr_p50_ms': round(median(samples[name]), 3),
                    'screen': menu_name(document, result),
                    # Also compare the OCR-only classifier; calibrated image
                    # recognition would otherwise hide dropped menu evidence.
                    'ocr_menu_agreement': menu_name(document, {'screen': 'unknown'}) ==
                                          menu_name(baseline, {'screen': 'unknown'}),
                    'screen_agreement': menu_name(document, result) == base_screen,
                    'pixels': pixels, 'rejected_boundary_lines': rejected,
                    **comparison,
                }
            rows.append(row)
    finally:
        reader.close()
    summary = {}
    for name in variants:
        values = [row['variants'][name] for row in rows]
        summary[name] = {
            'frames': len(values),
            'ocr_p50_ms': round(median(v['ocr_p50_ms'] for v in values), 3) if values else None,
            'menu_agreement_frames': sum(v['screen_agreement'] for v in values),
            'ocr_only_menu_agreement_frames': sum(v['ocr_menu_agreement'] for v in values),
            'frames_losing_actions': sum(bool(v['lost_actions']) for v in values),
            'actions_retained': sum(v['baseline_action_count']-len(v['lost_actions']) for v in values),
            'baseline_actions': sum(v['baseline_action_count'] for v in values),
            'frames_losing_danger': sum(bool(v['lost_danger']) for v in values),
            'danger_positive_frames': sum(bool(v['baseline_danger']) for v in values),
            'actual_sync_positive_frames': sum(bool(v['baseline_sync']) for v in values),
            'token_retention_p50': round(median(v['token_retention'] for v in values), 4) if values else None,
        }
    return {'research_only': True, 'repeats': repeats, 'summary': summary,
            'limitations': [
                'Reference is full-frame OCR, not human-labelled ground truth.',
                'Menu agreement alone does not prove retained action, identity, or resource evidence.',
                'Home crops omit pixels and cannot guard arbitrary-position overlays.',
                'Actual sync-positive coverage must be established separately; zero positive frames is no validation.',
                'Packed full-width bands cover every pixel but may split lines at band edges.',
                'Measured while the game may be running; no claimed live-cycle improvement.',
            ], 'skipped': skipped, 'frames': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('paths', nargs='*', type=Path)
    args = parser.parse_args()
    paths = args.paths or [core.BASE/'video_review'/f'frame_{second:06.2f}.jpg'
                           for second in DEFAULT_SECONDS] + [
        core.BASE/'failures'/f'{name}.png' for name in DEFAULT_FAILURES]
    report = benchmark(paths, args.repeats)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'summary': report['summary'], 'skipped': report['skipped'],
                      'limitations': report['limitations']}, indent=2))


if __name__ == '__main__':
    main()
