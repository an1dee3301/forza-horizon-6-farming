"""Current menu balance proofs and same-process repeat-farm car identity.

Neither disk balances nor estimates can create an SP proof. Menu proofs are
invalidated by every input/capture/focus change, separately from mastery tokens.
"""
import time
from dataclasses import asdict, dataclass

from .menu_sp import verify_menu_sp


@dataclass(frozen=True)
class MenuBalance:
    points: int
    observation: object
    observed_at: float
    identity: tuple
    generation: int


def game_identity(nav):
    provider=getattr(getattr(nav,'setup_checks',None),'identity',None)
    value=provider() if callable(provider) else None
    if not isinstance(value,(list,tuple)) or len(value)!=1 or not isinstance(value[0],str) or not value[0]:
        return None
    return tuple(value)


def recent_menu_sp(nav):
    proof=getattr(nav,'_menu_sp_proof',None)
    if not isinstance(proof,MenuBalance) or getattr(nav,'fast_navigation',False) is not True:
        return None
    if not 0<=time.monotonic()-proof.observed_at<=.75:
        return None
    nav.check()
    if (getattr(nav,'_menu_sp_proof',None) is not proof or nav.last is not proof.observation
            or nav.focus_generation!=proof.generation or game_identity(nav)!=proof.identity
            or not 0<=time.monotonic()-proof.observed_at<=.75):
        return None
    nav.sync_guard.require_verified(proof.identity)
    nav.check()
    if (getattr(nav,'_menu_sp_proof',None) is not proof or nav.last is not proof.observation
            or nav.focus_generation!=proof.generation or game_identity(nav)!=proof.identity
            or not 0<=time.monotonic()-proof.observed_at<=.75):
        return None
    return proof


def menu_reading_available(nav):
    tag=getattr(getattr(nav,'account_observer',None),'gamertag',None)
    return isinstance(tag,str) and bool(tag.strip()) and getattr(nav,'fast_navigation',False) is True


def read_tile_sp(nav):
    if not menu_reading_available(nav):
        return None
    tag=nav.account_observer.gamertag
    started=time.monotonic()
    nav.check()
    pinned=game_identity(nav)
    generation=nav.focus_generation
    if pinned is None:
        return None
    points=verify_menu_sp(nav,tag)
    verified_at=time.monotonic()
    if points is None:
        return None
    obs=nav.last
    if game_identity(nav)!=pinned:
        return None
    nav.check()
    nav.sync_guard.require_verified(pinned)
    nav.check()
    if (nav.last is not obs or nav.focus_generation!=generation
            or getattr(obs,'focus_generation',None)!=generation or game_identity(nav)!=pinned
            or not 0<=time.monotonic()-verified_at<=.75):
        return None
    nav._menu_sp_proof=MenuBalance(points,obs,verified_at,pinned,generation)
    nav.emit('log',f'Verified menu SP: {points} (two fresh Cars badge/tile readings; tree skipped; {time.monotonic()-started:.3f}s).')
    return points


def remember_farm_tree(nav,profile):
    """Caller has freshly verified the current Subaru's owned mastery tree."""
    identity=game_identity(nav)
    if identity is not None:
        nav._farm_tree_proof=(identity,nav.setup_checks.run_id,asdict(profile))


def menu_farm_ready(nav,profile,obs, *, selected=False):
    """Only reuse tree ownership on a same-process repeat with current car proof."""
    from .farming import farm_car
    from .ocr import Document
    import forza_cycle as core
    from .pause_mastery import target_title
    proof=getattr(nav,'_farm_tree_proof',None)
    if (not isinstance(proof,tuple) or len(proof)!=3 or
            not (getattr(nav,'_farm_pause_balance',False) is True or
                 (selected and getattr(nav,'_farm_selected_from_pause',False) is True)) or target_title(obs) is None):
        return False
    identity=game_identity(nav)
    if identity is None or proof!=(identity,nav.setup_checks.run_id,asdict(profile)):
        return False
    generation=nav.focus_generation
    nav.check()
    nav.sync_guard.require_verified(identity)
    if (nav.last is not obs or nav.focus_generation!=generation
            or getattr(obs,'focus_generation',None)!=generation or game_identity(nav)!=identity):
        return False
    # This top-left native header identifies the current car, not a tile image.
    lines=[line for line in obs.doc.lines if 500<=line.center[0]<1010 and 45<=line.center[1]<170]
    matched=farm_car(Document(lines),profile)
    if not matched:
        # Full-frame OCR omits characters in the native Subaru header on the
        # recorded 754-SP frame. Its native-sized exact header crop is legible;
        # keep the complete year/manufacturer/model predicate unchanged.
        matched=farm_car(nav.reader.read(core.crop(obs.frame,(535,100,485,75))),profile)
    nav.check()
    return (matched and nav.last is obs and nav.focus_generation==generation
            and game_identity(nav)==identity)


def selected_farm_balance(nav, profile):
    """Reuse owned-tree proof after selection; balance is always freshly read."""
    if (getattr(nav, '_farm_selected_from_pause', False) is not True or
            not isinstance(getattr(nav, '_farm_tree_proof', None), tuple)):
        return None
    nav.pause_tab('CARS')
    if not menu_farm_ready(nav, profile, nav.observe(), selected=True):
        return None
    points = read_tile_sp(nav)
    if points is not None:
        nav._farm_pause_balance = True
        nav._farm_selected_from_pause = False
        nav.emit('log', 'Selected Subaru matched this process’s owned-tree proof; fresh menu SP replaces mastery entry.')
    return points
