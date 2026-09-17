"""Refill SP for one paid partial Mazda without another purchase."""
import json
import forza_cycle as core
from .production import GoalSession
from .session import Session
from .reporting import read_json, write_json
from .farming import Challenge
from .garage import set_favorites
from .navigation import recent_sort_verified


def owned(obs):
    nodes = obs.result.get('nodes', {})
    if obs.screen != 'mad_mike_mastery' or set(nodes) != {n[0] for n in core.NODES}:
        raise RuntimeError('Recovery needs the exact Mad Mike mastery tree')
    if any(n.get('state') not in {'owned','available','unavailable','locked'} for n in nodes.values()):
        raise RuntimeError('Partial mastery is ambiguous')
    return sorted(k for k,v in nodes.items() if v['state']=='owned')


def recover(nav, emit):
    root = core.BASE/'runs'
    goal, cars = GoalSession(root/'goal.json'), Session()
    ledger = core.PurchaseLedger(); ledger.ready()
    receipt = read_json(ledger.path)
    if (cars.data.get('phase') != 'mastery' or cars.data.get('bought') != cars.data.get('completed',0)+1
            or (goal.data.get('batch') or {}).get('id') != cars.data.get('id')
            or receipt.get('status') not in {'confirmed','resolved_bought'}):
        raise RuntimeError('No confirmed paid partial copy to recover')
    path=root/'paid_sp_recovery.json'
    state=read_json(path)
    if state and (state['session'] != cars.data['id'] or state['receipt'] != receipt['id']):
        raise RuntimeError('Paid recovery identity changed')
    if not state:
        try:
            obs=nav.observe()
        except RuntimeError:
            obs=nav.last
            if not (obs is not None and obs.doc.has('Cannot Afford Perk') and
                    obs.doc.has('Perform skills in any car',contains=True) and
                    obs.doc.has('Enter',(0,940,300,140),contains=True)):
                raise
            nav.check()
            nav.key('enter')  # The exact resource notice only acknowledges OK.
            nav.pause(.5)
            obs=nav.wait('mad_mike_mastery')
        signature=owned(obs)
        second=nav.observe()
        if owned(second)!=signature:
            raise RuntimeError('Partial mastery did not agree on fresh frames')
        state=dict(session=cars.data['id'],receipt=receipt['id'],owned=signature,phase='farm')
        write_json(path,state)
    if state['phase']=='farm':
        emit('status','Refilling SP for the saved paid Mazda; no new purchases')
        challenge=Challenge(nav,path=root/'paid_sp_challenge.json',emit=emit)
        challenge.target_sp=999
        points=challenge.run(goal.data['id']+'_paid_sp_repair',return_collection=True)
        if points<21:
            raise RuntimeError('Recovery farm has not banked enough SP')
        state.update(phase='select',points=points);write_json(path,state)
    if state['phase']=='select':
        # No purchases or deletions occur in this repair. The first freshly
        # sorted car must be the last receipt, then its partial tree must match.
        if read_json(ledger.path).get('id')!=state['receipt']:
            raise RuntimeError('Another purchase occurred during paid recovery')
        current=nav.observe()
        if current.screen in {'sort_selection','recent_jump'}:
            nav.key('esc');nav.wait('garage_grid',previous=current.screen)
        nav.my_cars();set_favorites(nav,False)
        nav.key('x');nav.wait('sort_selection',previous='garage_grid')
        nav.click_label('sort_selection','Recently Added')
        nav.wait('garage_grid',previous='sort_selection',predicate=recent_sort_verified)
        nav.key('backspace');nav.wait('recent_jump',previous='garage_grid')
        nav.click_label('recent_jump','All Cars',(250,250,1410,650))
        obs=nav.wait('garage_grid',previous='recent_jump',predicate=recent_sort_verified)
        from .navigation import selected_card
        from .current_car import FIRST_CARD
        if any(abs(a-b)>3 for a,b in zip(selected_card(obs.frame),FIRST_CARD)):
            raise RuntimeError('Newest card is not selected; paid copy not inferred')
        nav.enter_fresh_car(obs,require_new=False)
        tree=nav.open_mastery()
        if owned(tree)!=state['owned'] or owned(nav.observe())!=state['owned']:
            raise RuntimeError('Newest Mazda does not match the saved partial tree')
        points=nav.available_sp()
        if points<21:raise RuntimeError('Recovery balance no longer covers the remaining tree')
        # Finish only this paid copy, then force a fresh menu SP read.
        batch=dict(goal.data['batch'],cycles=cars.data['completed']+1-goal.data['batch']['completed_start'])
        goal.save(batch=batch,last_sp=points,challenge_sp_rewards=-1)
        cars.save(limit=cars.data['completed']+1)
        state.update(phase='complete');write_json(path,state)
    emit('status','Paid Mazda reselected and partial tree verified; ready to finish mastery')


def main():
    """Resume production only after the recovery worker exits successfully."""
    import argparse
    import subprocess
    import sys
    from .cleanup_resume import wait_process
    parser=argparse.ArgumentParser()
    parser.add_argument('--wait-pid',type=int,required=True)
    args=parser.parse_args()
    wait_process(args.wait_pid)
    root=core.BASE/'runs'
    state=read_json(root/'paid_sp_recovery.json')
    cars=Session().data
    goal=GoalSession(root/'goal.json').data
    if (state.get('phase')!='complete' or state.get('session')!=cars.get('id')
            or cars.get('phase')!='mastery' or goal.get('phase')!='convert'):
        return 1  # Includes F7 and every failed identity/farming check.
    subprocess.Popen([sys.executable,str(core.BASE/'Forza-Horizon-6-Wheelspin-Macro-main/Runtime/bridge.py'),
        '--channel',str(root/'resume_after_paid_repair'),'--action','run',
        '--mode','Earn saved Super Wheelspins','--target',str(goal['limit']),
        '--reserve',str(goal.get('reserve_sp',0)),'--resume-goal-id',goal['id']],
        cwd=core.BASE,creationflags=subprocess.CREATE_NO_WINDOW)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
