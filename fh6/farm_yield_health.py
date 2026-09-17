"""Detect substantial full-run yield losses without borrowing top-up samples."""
from math import isfinite
from statistics import median


def assess(current, history, nominal_seconds):
    def eligible(row):
        drive, gain = row.get('drive_seconds'), row.get('gained_sp')
        return (row.get('share_code') == current.get('share_code')
                and row.get('exit_reason') == 'natural_completion'
                and not row.get('capped') and not row.get('partial_timing')
                and isinstance(drive, (int, float)) and isfinite(drive)
                and nominal_seconds*.9 <= drive <= nominal_seconds*1.25
                and isinstance(gain, (int, float)) and isfinite(gain) and 0 <= gain < 999)

    samples = [r['gained_sp'] for r in history
               if (not current.get('id') or r.get('id') != current['id']) and eligible(r)][-10:]
    result = dict(samples=len(samples), degraded=False, basis='full_uncapped_same_challenge')
    if not eligible(current) or len(samples) < 3:
        return result
    expected = float(median(samples))
    result.update(expected_sp=expected, observed_sp=current['gained_sp'],
                  threshold_sp=expected*.6,
                  degraded=expected >= 21 and current['gained_sp'] < expected*.6)
    return result
