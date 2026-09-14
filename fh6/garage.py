"""Shared, explicit garage-filter state for farming and purchased cars.

Checkbox recognition is calibrated from the local game. Missing or ambiguous
calibration stops navigation instead of guessing whether Favorites is active.
"""
import json
from pathlib import Path

import cv2
import numpy as np
import forza_cycle as core


FILTER_REGION = (250, 150, 1420, 800)


class FilterNotReady(RuntimeError):
    """A visible filter is still moving or has no unique visual state yet."""


def filter_dialog(doc):
    return (any(doc.has(s, FILTER_REGION, contains=True) for s in
                ('Filter', 'Filter Selection', 'Filter Cars', 'Filter By')) and
            (any(doc.has(s, FILTER_REGION) for s in ('Favorites', 'Favourites')) or
             (doc.has('Filter', (620,175,690,75)) and
              doc.has('Toggle', (65,975,1700,65), contains=True) and
              doc.has('Reset', (65,975,1700,65), contains=True))))


def favorite_label(doc):
    labels = doc.find('Favorites', FILTER_REGION) + doc.find('Favourites', FILTER_REGION)
    if len(labels) != 1:
        raise FilterNotReady('Favorites filter label is ambiguous')
    return labels[0]


class FilterReader:
    def __init__(self, path=core.BASE/'calibration/garage_filter.json'):
        self.path = Path(path)

    def validate(self):
        if not self.path.exists():
            raise RuntimeError('Garage filter needs local checkbox calibration before starting the mission')
        spec = json.loads(self.path.read_text(encoding='utf-8'))
        bounds = spec.get('interior_from_label', [])
        if len(bounds) != 4 or any(type(n) is not int for n in bounds) or min(bounds[2:]) <= 0:
            raise RuntimeError('Invalid garage filter calibration bounds')
        for state in ('on', 'off'):
            if not spec.get(state):
                raise RuntimeError('Both checked and unchecked filter appearances must be calibrated')
            for filename in spec[state]:
                path = (self.path.parent/filename).resolve()
                if not path.is_relative_to(self.path.parent.resolve()):
                    raise RuntimeError('Invalid garage filter template path')
                frame = cv2.imread(str(path))
                if frame is None or frame.shape[:2] != (bounds[3], bounds[2]):
                    raise RuntimeError('Missing or invalid garage filter template')
        return spec

    def state(self, obs):
        if not filter_dialog(obs.doc) or not self.path.exists():
            raise RuntimeError('Garage filter needs local checkbox calibration before automatic selection')
        spec = self.validate()
        label = favorite_label(obs.doc)
        dx, dy, width, height = spec['interior_from_label']
        x, y = label.box[:2]
        patch = core.crop(obs.frame, (x+dx, y+dy, width, height))
        scores = {}
        for state in ('on', 'off'):
            errors = []
            for filename in spec[state]:
                template_path = (self.path.parent/filename).resolve()
                if not template_path.is_relative_to(self.path.parent.resolve()):
                    raise RuntimeError('Invalid garage filter template path')
                template = cv2.imread(str(template_path))
                if template is None or patch.shape != template.shape:
                    raise RuntimeError('Garage filter template is missing or has changed size')
                errors.append(float(np.mean(np.abs(patch.astype(float)-template.astype(float)))))
            scores[state] = min(errors)
        selected = min(scores, key=scores.get)
        if scores[selected] > spec.get('max_error', 12) or abs(scores['on']-scores['off']) < spec.get('min_gap', 15):
            raise FilterNotReady('Favorites checkbox is ambiguous; no filter input sent')
        return selected == 'on'


def wait_filter(nav, reader, expected=None, previous=()):
    """Wait for matching checkbox readings, not just a readable dialog title.

    Only transient visual ambiguity can wait. Invalid calibration, sync errors,
    unexpected screens and the navigation timeout still stop immediately.
    """
    last = None
    state = None

    def settled(obs):
        nonlocal last, state
        try:
            state = reader.state(obs)
        except FilterNotReady:
            last = None
            return False
        same = last is None or state is last
        last = state
        return same and (expected is None or state is expected)

    obs = nav.wait('garage_filter', previous=previous, predicate=settled)
    return obs, state


def set_favorites(nav, enabled, reader=None):
    reader = reader or FilterReader()
    obs = nav.wait({'garage_grid', 'garage_filter'})
    if (not enabled and obs.screen == 'garage_grid'
            and getattr(nav, 'fast_navigation', False) is True
            and getattr(nav, 'garage_filters_clear', False) is True
            and obs.doc.has('Filter', (65, 975, 1700, 65), contains=True)):
        nav.check()
        nav.emit('log', 'Garage filters remain verified clear; skipping repeat filter reset.')
        return obs
    nav.garage_filters_clear = False
    if obs.screen == 'garage_grid':
        if not obs.doc.has('Filter', (65, 975, 1700, 65), contains=True):
            raise RuntimeError('My Cars filter control is not visible')
        nav.key('y')
        obs, before = wait_filter(nav, reader, previous='garage_grid')
    else:
        obs, before = wait_filter(nav, reader)
    if not enabled:
        if not obs.doc.has('Reset', (65,975,1700,65), contains=True):
            raise RuntimeError('Garage filter Reset control is not visible')
        # Reset clears every filter, including selections below the scroll area.
        nav.key('x')
        wait_filter(nav, reader, expected=False)
        nav.key('esc')
        result = nav.wait('garage_grid', previous='garage_filter')
        nav.garage_filters_clear = True
        return result
    if before != enabled:
        label = favorite_label(obs.doc)
        # A generic click-and-Enter fallback would toggle a checkbox twice.
        nav.keyboard_select({'garage_filter'}, label.text, FILTER_REGION)
        wait_filter(nav, reader, expected=enabled)
    nav.key('esc')
    return nav.wait('garage_grid', previous='garage_filter')
