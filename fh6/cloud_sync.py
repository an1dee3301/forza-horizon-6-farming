"""Cloud-save synchronization blocks mission input and crash recovery.

No buttons on cloud, offline, conflict, or account dialogs are selected here.
The gate persists across worker restarts and has no time-based bypass.
"""
import json
import uuid
import re
from pathlib import Path

import forza_cycle as core
from .ocr import normalize


class SyncPending(RuntimeError):
    pass


def confirm_current_sync(path=core.BASE/'runs/cloud_sync.json'):
    """Called only by the user's explicit sync-confirmation control."""
    path = Path(path)
    request = json.loads(path.read_text(encoding='utf-8'))
    if not request.get('request_id'):
        raise RuntimeError('No current sync verification request')
    answer = path.with_suffix('.confirmed.json')
    temp = answer.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(request_id=request['request_id'], confirmed=True)), encoding='utf-8')
    temp.replace(answer)


def sync_state(doc):
    text = normalize(' '.join(line.text for line in doc.lines))
    if any(s in text for s in ('stop syncing', 'play offline', 'can t sync',
                               'cannot sync', 'unable to sync', 'sync conflict',
                               'which save', 'newer in the cloud')):
        return 'attention'
    if any(s in text for s in ('syncing data', 'syncing your data', 'synchronizing',
                               'sync in progress', 'synchronization in progress')):
        return 'syncing'
    return None


class SyncGuard:
    def __init__(self, windows, running, emit=lambda *a: None,
                 path=core.BASE/'runs/cloud_sync.json'):
        self.windows, self.running, self.emit, self.path = windows, running, emit, Path(path)
        self.pending = self.path.exists()
        self.announced = False
        self.evidence = None
        self.verified_identity = None
        self.saw_final_progress = False
        self.wait_identity = None

    def observe_wait_identity(self, identity):
        """Completion observed for one process cannot release another process."""
        identity = tuple(identity)
        changed = self.wait_identity is not None and identity != self.wait_identity
        self.wait_identity = identity
        if changed:
            # Issue a new request too: an old manual confirmation may otherwise
            # race a game exit/relaunch while synchronization is still pending.
            self.pending = False
            self.block('Game process changed while waiting for full synchronization')
            self.path.with_suffix('.confirmed.json').unlink(missing_ok=True)
        return changed

    def block(self, reason):
        if not self.pending:
            self.evidence = None
            self.saw_final_progress = False
            self.path.with_suffix('.verified.json').unlink(missing_ok=True)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps({'state': 'waiting', 'reason': reason,
                                       'request_id': uuid.uuid4().hex}), encoding='utf-8')
            temp.replace(self.path)
        self.pending = True
        self.verified_identity = None
        if not self.announced:
            self.emit('stage', 'cloud_sync')
            self.emit('status', 'Waiting for full cloud sync. No offline mode, mission input or restart. F7 stops.')
            self.announced = True

    def visible(self):
        return bool(self.windows())

    def check(self):
        if not self.running.is_set():
            raise core.MasteryStopped('Stopped with F7')
        if self.visible():
            self.block('Gaming UI / cloud dialog is open')
        if self.pending:
            raise SyncPending('Cloud sync must finish before any mission input')

    def inspect(self, doc):
        state = sync_state(doc)
        if state:
            self.block(state)
            raise SyncPending('Cloud sync is unfinished or needs attention')

    def observe_completion(self, doc):
        state = sync_state(doc)
        text = ' '.join(line.text for line in doc.lines)
        if state == 'syncing':
            # Final progress is only a milestone. Input stays blocked until
            # the dialog closes and the lifecycle verifies stable game UI.
            # A retry or another unfinished stage invalidates an earlier 100%
            # or completion message, even if the process identity is unchanged.
            self.evidence = None
            progress = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%', text)
            if progress:
                self.saw_final_progress = all(float(value) == 100 for value in progress)
                if not self.saw_final_progress:
                    self.path.with_suffix('.confirmed.json').unlink(missing_ok=True)
            return
        if state == 'attention':
            self.evidence = None
            self.saw_final_progress = False
            self.path.with_suffix('.confirmed.json').unlink(missing_ok=True)
            return
        if not sync_state(doc) and any(doc.has(s) for s in
                ('Sync complete', 'Synchronization complete', 'Cloud sync complete')):
            self.evidence = 'Visible explicit cloud-sync completion'

    def native_startup_complete(self, launched, sent):
        """Recognize completion of the startup flow owned by this worker.

        Merely attaching to a playable menu is insufficient. The worker must
        have launched the process (or selected Start Game) and selected Continue,
        without cancelling or bypassing a synchronization dialog.
        """
        self.check()
        if 'continue' in sent and (launched or 'start' in sent):
            self.evidence = 'Observed native startup through Continue to the ready game'

    def playable_ui_complete(self, identity, screen):
        """Accept repeated native playable UI as process-bound sync proof.

        The lifecycle owns the stability counter and calls this only after the
        same recognized playable screen has been visible for three captures,
        with no Gaming UI/cloud window and no sync/offline/conflict text.  A
        playable menu cannot coexist with an unfinished cloud-sync dialog, so
        holding the worker for a historical completion message only wastes
        time when it attaches to an already-running game.
        """
        identity = list(identity)
        if not identity or self.visible():
            return False
        self.evidence = f'Observed stable playable {screen} UI for current game process'
        self.verified_identity = identity
        self.save_proof()
        return True

    def require_verified(self, identity):
        self.check()
        identity = list(identity)
        if self.verified_identity is not None and self.verified_identity != identity:
            self.evidence = None
        proof = self.path.with_suffix('.verified.json')
        if not self.evidence and proof.exists():
            try:
                saved = json.loads(proof.read_text(encoding='utf-8'))
                if saved.get('identity') == identity:
                    self.evidence = saved['evidence']
            except (OSError, ValueError, KeyError):
                pass
        if self.verified_identity != identity:
            if self.evidence:
                self.verified_identity = identity
                self.save_proof()
            else:
                self.block('Cloud sync completion has not been verified for this game process')
                raise SyncPending('Verify full cloud sync before starting the mission')

    def save_proof(self):
        proof = self.path.with_suffix('.verified.json')
        temp = proof.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(identity=self.verified_identity, evidence=self.evidence)), encoding='utf-8')
        temp.replace(proof)

    def confirmation(self):
        try:
            request = json.loads(self.path.read_text(encoding='utf-8'))
            answer = json.loads(self.path.with_suffix('.confirmed.json').read_text(encoding='utf-8'))
            return bool(request.get('request_id') and answer.get('request_id') == request['request_id']
                        and answer.get('confirmed') is True)
        except (OSError, ValueError):
            return False

    def ready(self):
        """Stable UI is required in addition to explicit completion evidence."""
        if self.wait_identity == ():
            return False
        if self.visible():
            self.block('Cloud dialog reopened')
            return False
        if self.saw_final_progress:
            self.evidence = 'Observed sync reach 100%, dialog close, and stable game UI'
        if not self.evidence and not self.confirmation():
            return False
        self.evidence = self.evidence or 'User confirmed full cloud sync for this request'
        if self.wait_identity is not None:
            self.verified_identity = list(self.wait_identity)
            self.save_proof()
        self.path.unlink(missing_ok=True)
        self.path.with_suffix('.confirmed.json').unlink(missing_ok=True)
        self.pending = False
        self.announced = False
        self.wait_identity = None
        self.emit('log', f'Cloud sync verified: {self.evidence}; stable game verified.')
        return True
