"""Versioned challenge settings, separate from navigation and job accounting."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from forza_cycle import BASE


@dataclass(frozen=True)
class ChallengeProfile:
    name: str = 'Mega Farm V6'
    share_code: str = '155439962'
    car: str = 'IMPREZA 22B-STi VERSION'
    manufacturer: str = 'SUBARU'
    year: str = '1998'
    duration_seconds: int = 900
    movement_interval: int = 240
    accelerator: str = 'w'
    movement_key: str = 'a'
    movement_seconds: float = .08
    source: str = 'https://www.reddit.com/r/ForzaHorizon6/comments/1w6xpvf/new_400sp15min_mega_farm_v6/'

    def validate(self):
        if not self.share_code.isdigit() or len(self.share_code) != 9:
            raise ValueError('Challenge share code must contain nine digits')
        if type(self.duration_seconds) is not int or not 30 <= self.duration_seconds <= 3600:
            raise ValueError('Challenge duration must be 30–3600 seconds')
        if type(self.movement_interval) is not int or not 10 <= self.movement_interval <= 240:
            raise ValueError('Movement interval must be 10–240 seconds')
        if self.accelerator != 'w' or self.movement_key not in ('a', 'd') or not 0 < self.movement_seconds <= .15:
            raise ValueError('Use the standard W accelerator and a short A/D steering pulse')
        if not all((self.name, self.car, self.manufacturer, self.year)):
            raise ValueError('The challenge and farm car must be identified')
        return self


PROFILE_PATH = BASE/'profiles'/'mega_v6.json'


def load_profile(path=PROFILE_PATH):
    path = Path(path)
    if not path.exists():
        return ChallengeProfile().validate()
    return ChallengeProfile(**json.loads(path.read_text(encoding='utf-8'))).validate()


def save_profile(profile, path=PROFILE_PATH):
    profile.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(asdict(profile), indent=2), encoding='utf-8')
    temp.replace(path)
