"""Profile-verified repeat route: read mastery SP without repeated house travel."""
import forza_cycle as core
from .analytics import read

OPTIMIZATION_VERSION='mini_repeat_v2'


MEGA_PAUSE_ROUTE_VERSION = 'mega_pause_route_v1'
MEGA_ROUTE_CHECKS = (
    'subaru_tree', 'two_frame_sp', 'home_sp_crosscheck',
    'return_to_pause', 'repeat_exact_challenge', 'post_run_retained_sp',
)


def enabled(nav, profile):
    setup=getattr(nav,'setup_checks',None)
    rollout=read(core.BASE/'runs/farm_optimization.json')
    if (setup is None or rollout.get('goal_id') != setup.run_id or
            rollout.get('optimization_version') != OPTIMIZATION_VERSION):
        return False
    code = getattr(profile, 'share_code', None)
    if code == '169055890':
        # Preserve the existing Mini gate; Mega proof never enables it.
        return rollout.get('pause_mastery_verified') is True
    if code != '155439962':
        return False
    proofs = rollout.get('pause_mastery_profiles')
    proof = proofs.get(code) if isinstance(proofs, dict) else None
    if not isinstance(proof, dict):
        return False
    from dataclasses import asdict
    from .profiles import ChallengeProfile
    if not isinstance(profile, ChallengeProfile):
        return False
    checks = proof.get('checks')
    evidence = proof.get('evidence')
    if (proof.get('verified') is not True or
            proof.get('goal_id') != setup.run_id or
            proof.get('route_version') != MEGA_PAUSE_ROUTE_VERSION or
            proof.get('profile') != asdict(profile) or
            not isinstance(checks, dict) or
            not all(checks.get(name) is True for name in MEGA_ROUTE_CHECKS) or
            not isinstance(evidence, list) or not evidence or
            not all(isinstance(item, str) and item.strip() for item in evidence)):
        return False
    try:
        identity = setup.identity()
        return bool(isinstance(identity, list) and identity and
                    proof.get('game_identity') == identity and setup.reusable(profile))
    except (OSError, TypeError, ValueError):
        # Optional route proof never authorizes a guess on a failed identity read.
        return False


def verified_tree(nav, obs, profile):
    from .farming import farm_car, farm_tree_owned
    return (obs.screen=='car_mastery' and
            farm_car(nav.reader.read(core.crop(obs.frame,(810,190,610,100))),profile)
            and farm_tree_owned(obs.frame))


def read_after_run(nav, profile):
    """The existing home route remains the fallback for an unavailable tile."""
    nav._farm_pause_mastery=False
    nav._farm_pause_balance=False
    nav._farm_mastery_origin_unknown=False
    from .farm_balance import menu_reading_available
    if not enabled(nav,profile) and not menu_reading_available(nav):
        nav.ensure_home()
        return nav.available_sp()
    obs=nav.observe()
    if obs.screen=='car_mastery':
        # A guarded interruption can leave the already-entered Subaru tree
        # open. Re-prove current profile/tree and actual SP before any travel.
        if not verified_tree(nav,obs,profile):
            raise RuntimeError('Resumed mastery is not the verified maxed Subaru; no farm balance accepted')
        nav.until(lambda current:verified_tree(nav,current,profile),
                  'resumed owned Subaru mastery',timeout=3)
        nav._verified_sp=None
        points=nav.available_sp()  # Two fresh agreeing actual balance frames.
        nav._farm_mastery_origin_unknown=True
        nav.emit('log','Recovered actual SP from the already-open owned Subaru tree; exit origin remains unverified.')
        return points
    if not (nav.is_roam(obs) or nav.is_pause(obs)):
        nav.ensure_home()
        return nav.available_sp()
    if nav.is_roam(obs):
        # Use the existing bounded reversible-Esc retry instead of waiting the
        # full screen timeout when the first pulse lands during exit animation.
        nav.open_pause_menu('free-roam menu for SP check')
    nav.pause_tab('CARS')
    from .farm_balance import read_tile_sp
    points=read_tile_sp(nav)
    if points is not None:
        nav._farm_pause_balance=True
        return points
    if not enabled(nav,profile):
        nav.ensure_home()
        return nav.available_sp()
    from .pause_mastery import open_pause_mastery
    if not open_pause_mastery(nav):
        nav.ensure_home()
        return nav.available_sp()
    tree=nav.until(lambda o:o.screen=='car_mastery','Subaru mastery from pause')
    if not verified_tree(nav,tree,profile):
        raise RuntimeError('Pause mastery is not the verified maxed Subaru; no farm balance accepted')
    points=nav.available_sp()  # Two independent matching actual SP observations.
    nav._farm_pause_mastery=True
    nav.emit('log',getattr(profile, 'name', 'Farm')+' retained SP verified from pause mastery; skipped entering home.')
    return points


def prepare_search(nav, profile):
    """Stay outside only with current-process setup and current Subaru proof."""
    setup=getattr(nav,'setup_checks',None)
    if getattr(nav,'_farm_direct_pause_tree',False) is True:
        nav._farm_direct_pause_tree=False
        if not verified_tree(nav,nav.observe(),profile):
            raise RuntimeError('Pause farm tree changed before exit')
        nav.key('esc')
        nav.until(nav.is_pause,'pause after verifying Subaru mastery')
        if setup is not None and setup.reusable(profile):
            nav.ensure_farm_settings(profile)
            nav.emit('log','Subaru tree verified from pause; search continues outside Home.')
            return
    from .farm_balance import menu_farm_ready
    if (getattr(nav,'_farm_pause_balance',False) is True and
            menu_farm_ready(nav,profile,nav.observe()) and setup.reusable(profile)):
        nav._farm_pause_balance=False
        nav.ensure_farm_settings(profile)
        nav.emit('log','Repeat search directly from verified Cars menu; no mastery entry/exit or house travel.')
        return
    if (getattr(nav,'_farm_mastery_origin_unknown',False) is True and
            enabled(nav,profile) and setup.reusable(profile) and
            verified_tree(nav,nav.observe(),profile)):
        nav._farm_mastery_origin_unknown=False
        nav._farm_pause_mastery=False
        nav.key('esc')
        last_kind=None
        def recovered_destination(obs):
            nonlocal last_kind
            kind=('pause' if nav.is_pause(obs) else
                  'home' if nav.is_home(obs) or obs.screen=='upgrades' else None)
            same=kind is not None and (last_kind is None or kind==last_kind)
            last_kind=kind
            return same
        destination=nav.until(recovered_destination,'pause or home after recovered farm SP check')
        if nav.is_pause(destination):
            nav.emit('log','Recovered Subaru mastery exited to verified pause; skipping house travel.')
        else:
            nav.ensure_home()
        nav.ensure_farm_settings(profile)
        return
    nav._farm_mastery_origin_unknown=False
    if (enabled(nav,profile) and getattr(nav,'_farm_pause_mastery',False)
            and setup.reusable(profile) and verified_tree(nav,nav.observe(),profile)):
        nav.key('esc')
        nav.until(nav.is_pause,'pause menu after farm SP check')
        nav._farm_pause_mastery=False
        nav.emit('log',getattr(profile, 'name', 'Farm')+' repeat from pause; skipped leaving home.')
    else:
        nav._farm_pause_mastery=False
        prior = getattr(nav, '_farm_setup_home_return', False)
        nav._farm_setup_home_return = getattr(profile, 'share_code', None) in {'169055890', '155439962'}
        try:
            nav.ensure_home()
        finally:
            nav._farm_setup_home_return = prior
    nav.ensure_farm_settings(profile)
