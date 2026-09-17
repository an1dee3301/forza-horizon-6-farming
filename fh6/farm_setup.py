"""Retain stable farm settings for one mission, independently of worker retries."""
import json
from dataclasses import asdict
from pathlib import Path

from forza_cycle import BASE
from .session import replace_checkpoint


VIDEO_POLICY='crash_safe_43_fps_v3'
DIFFICULTY_POLICY='mega_manual_first_v1'


class FarmSetupChecks:
    def __init__(self, run_id, identity, path=BASE/'runs/farm_setup.json'):
        self.run_id, self.identity, self.path = run_id, identity, Path(path)

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        replace_checkpoint(temporary, self.path)

    def invalidate_video(self):
        data = self.read()
        if data.get('run_id') == self.run_id:
            data['video_identity'] = None
            self.save(data)

    def reusable(self, profile):
        data=self.read()
        return (data.get('run_id')==self.run_id and data.get('profile')==asdict(profile)
                and data.get('video_identity')==self.identity()
                and data.get('video_policy')==VIDEO_POLICY
                and data.get('difficulty_policy')==DIFFICULTY_POLICY)

    def ensure(self, profile, full_check, video_check):
        profile_data, identity = asdict(profile), self.identity()
        data = self.read()
        if (data.get('run_id') != self.run_id or data.get('profile') != profile_data
                or data.get('difficulty_policy') != DIFFICULTY_POLICY):
            full_check()
            result = 'full'
        elif data.get('video_identity') != identity or data.get('video_policy') != VIDEO_POLICY:
            video_check()
            result = 'video'
        else:
            return 'cached'
        # Never promote a failed check or proof from a process that just exited.
        if identity != self.identity():
            raise RuntimeError('Game changed during farm settings verification')
        self.save(dict(run_id=self.run_id, profile=profile_data, video_identity=identity,
                       video_policy=VIDEO_POLICY, difficulty_policy=DIFFICULTY_POLICY))
        return result
