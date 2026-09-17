"""Fresh countdown and process proof for farm throttle acquisition."""
import time
from .farm_polling import active_countdown_only


class ThrottleProof:
    def __init__(self, nav, profile, remaining_seconds, clock=time.monotonic):
        self.nav, self.profile, self.remaining_seconds, self.clock = nav, profile, remaining_seconds, clock
        if type(getattr(nav, 'focus_generation', None)) is not int:
            raise RuntimeError('Farm input requires foreground generation tracking')
        self.provider = getattr(getattr(nav, 'setup_checks', None), 'identity', None)
        if not callable(self.provider):
            raise RuntimeError('Farm input requires current game identity')
        nav.check()
        self.identity = self.current_identity()
        self.generation = nav.focus_generation
        self.previous = self.current = self.last_accepted = None
        self.stamp = 0.0

    def current_identity(self):
        value = self.provider()
        if not isinstance(value, (list, tuple)) or len(value) != 1 or not isinstance(value[0], str) or not value[0]:
            raise RuntimeError('Farm game process identity is unavailable or ambiguous')
        return tuple(value)

    def changed(self):
        return self.nav.focus_generation != self.generation

    def reset(self):
        self.generation = self.nav.focus_generation
        self.previous = self.current = None

    def observe(self, obs):
        if self.changed():
            self.reset()
        remaining = self.remaining_seconds(obs.doc)
        # Mega's observed native countdown includes an initial ~17s lead-in.
        # Use the existing drive deadline's +120s bound, not the nominal900s.
        active = (getattr(obs, 'focus_generation', None) == self.generation and
                  self.nav.last is obs and active_countdown_only(obs.doc, remaining) and
                  remaining <= self.profile.duration_seconds + 120)
        if not active:
            self.previous = self.current = None
            return False
        if self.current is not None and (self.current[0] is obs or
                getattr(self.current[0], 'frame', None) is getattr(obs, 'frame', None)):
            self.previous = self.current = None
            return False
        self.previous, self.current = self.current, (obs, remaining)
        self.stamp = self.clock()
        return self.previous is not None and remaining < self.previous[1]

    def run_input(self, action):
        """Run one input only from the current two-frame countdown proof."""
        nav = self.nav
        if self.previous is None or self.current is None or self.changed():
            return False
        obs, remaining = self.current
        if remaining >= self.previous[1] or nav.last is not obs:
            self.reset()
            return False
        ready = (obs, self.stamp)
        nav._ready = ready
        nav.check()
        if self.current_identity() != self.identity:
            raise RuntimeError('Game changed during farm throttle verification')
        nav.check()
        if (nav._ready is not ready or nav.last is not obs or self.changed() or
                getattr(obs, 'focus_generation', None) != self.generation or
                self.clock() - self.stamp > .08):
            nav.invalidate_ready()
            self.reset()
            return False
        nav.invalidate_ready()
        action()
        return True

    def press(self, key_down):
        if not self.run_input(lambda: key_down(self.profile.accelerator)):
            return False
        remaining = self.current[1]
        self.last_accepted = dict(previous_remaining_seconds=self.previous[1],
            remaining_seconds=remaining, focus_generation=self.generation,
            game_identity=list(self.identity))
        return True
