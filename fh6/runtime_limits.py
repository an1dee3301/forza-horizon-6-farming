"""Run permission: only an explicit stop clears it; elapsed time never does."""
from threading import Event


class RunSignal(Event):
    def configure(self, goal):
        # Legacy deadline fields are history, never a reason to disarm retries.
        # Loading a checkpoint must never undo an explicit F7 stop either.
        pass
