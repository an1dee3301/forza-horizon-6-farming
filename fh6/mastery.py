"""Mastery module: use the proven interior and caption checks for each Enter."""
import time
from forza_cycle import mastery_once


def claim(nav):
    started = time.perf_counter()
    mastery_once(nav.recognizer, nav.capture, nav.monitor, nav.title, nav.running,
                 fast=nav.fast_navigation)
    nav.emit('log', f'Mastery path verified in {time.perf_counter()-started:.2f} seconds.')
