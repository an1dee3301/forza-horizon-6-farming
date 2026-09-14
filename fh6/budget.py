"""Plan a finite purchase/mastery run from the user's skill-point balance."""
import re
from dataclasses import dataclass

from forza_cycle import NODES

POINTS_PER_CAR = sum(cost for _, _, _, cost in NODES)
CREDITS_PER_CAR = 95_000


@dataclass(frozen=True)
class SkillPlan:
    points: int
    cars: int
    points_used: int
    points_left: int
    credits: int
    reserve: int = 0


def whole_number(value, name):
    text = str(value).strip()
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', text):
        raise ValueError(f'{name} must be a whole number, zero or greater.')
    return int(text.replace(',', ''))


def plan_from_sp(value, reserve=0):
    points = whole_number(value, 'Current SP')
    reserve = whole_number(reserve, 'SP to keep')
    cars = max(0, points - reserve) // POINTS_PER_CAR
    used = cars * POINTS_PER_CAR
    return SkillPlan(points, cars, used, points - used, cars * CREDITS_PER_CAR, reserve)
