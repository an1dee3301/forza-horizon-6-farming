"""Read saved spin inventory from My Horizon; never infer it from earnings."""
from datetime import datetime
import os
from pathlib import Path
import re
import time

import cv2
import numpy as np


PROOF = 'two_fresh_my_horizon_frames'
ACCOUNT_BOX = (1300, 40, 440, 155)
TAB_BOX = (240, 200, 1440, 50)
SW_TITLE = (245, 550, 280, 125)
WS_TITLE = (1400, 550, 280, 100)
SW_COUNT = (245, 760, 275, 65)
WS_COUNT = (1400, 690, 275, 65)
AVAILABLE = re.compile(r'(0|[1-9]\d{0,8}|[1-9]\d{0,2}(?:,\d{3}){1,2})\s+Available', re.IGNORECASE)


def _inside(line, box):
    x,y,w,h=line.box;rx,ry,rw,rh=box
    return w>0 and h>0 and rx<=x and ry<=y and x+w<=rx+rw and y+h<=ry+rh


def read_inventory(obs, gamertag):
    """Return one native frame's exact labeled counts, or None.

    The full observation must already have passed Navigator's game/sync guards.
    Count ROIs exclude the capped yellow 99+ badges and other menu numbers.
    """
    from .report_images import allowed_report_menu
    frame=getattr(obs,'frame',None);doc=obs.doc
    if (frame is None or frame.shape!=(1080,1920,3) or not isinstance(gamertag,str)
            or not gamertag.strip() or not allowed_report_menu(obs.screen,doc)):
        return None
    account=doc.find(gamertag,ACCOUNT_BOX,contains=True)
    tabs=doc.find('MY HORIZON',TAB_BOX)
    if len(account)!=1 or not _inside(account[0],ACCOUNT_BOX) or len(tabs)!=1:
        return None
    x,y,w,h=tabs[0].box
    if not _inside(tabs[0],TAB_BOX):
        return None
    tab=frame[y-4:y+h+4,x-7:x+w+7]
    if np.mean(cv2.cvtColor(tab,cv2.COLOR_BGR2GRAY)<65)<=.55:
        return None
    if any(doc.has(label,contains=True) for label in (
            'Synchronizing','Syncing','Time Remaining','Quit Event','Restart Event',
            'Yes','No','Cancel','Confirm','Insufficient Credits')):
        return None
    if not all(len(doc.find(label,(65,980,290,60)))==1 for label in ('Enter','Select','Back')):
        return None
    sw=[line.text.strip().casefold() for line in doc.lines if _inside(line,SW_TITLE)]
    ws=[line.text.strip().casefold() for line in doc.lines if _inside(line,WS_TITLE)]
    if sw not in (['super','wheelspin'],['super wheelspin']) or ws!=['wheelspin']:
        return None
    result={}
    for key,box in (('super_wheelspins',SW_COUNT),('wheelspins',WS_COUNT)):
        labels=[line for line in doc.lines if _inside(line,box)]
        match=AVAILABLE.fullmatch(labels[0].text.strip()) if len(labels)==1 else None
        if match is None:
            return None
        result[key]=int(match[1].replace(',',''))
    return result


def verify_inventory(nav, gamertag, *, goal_id, root, worker_run=None,
                     mission_rewards=None, timeout=3.0, clock=time.monotonic):
    """Observe and save two fresh agreeing counts without sending inputs.

    The caller navigates to My Horizon. F7, focus, sync and the single native
    process identity remain guarded. A lower count is valid observed inventory.
    Only inventory_observed.json is written; goal/baseline/earnings stay intact.
    """
    from .reporting import now, read_json, write_json
    if not isinstance(goal_id,str) or not goal_id or not 0<timeout<=5:
        raise ValueError('Inventory verification needs a mission id and timeout in (0,5] seconds')
    provider=getattr(getattr(nav,'setup_checks',None),'identity',None)
    sync=getattr(nav,'sync_guard',None)
    if not callable(provider) or not callable(getattr(sync,'require_verified',None)):
        return None
    def identity():
        value=provider()
        if not isinstance(value,(list,tuple)) or len(value)!=1 or not isinstance(value[0],str) or not value[0]:
            raise RuntimeError('Current game identity unavailable for inventory reading')
        return tuple(value)
    deadline=clock()+timeout
    nav.check();pinned=identity();sync.require_verified(pinned)
    generation=getattr(nav,'focus_generation',None)
    if type(generation) is not int:
        return None
    previous,previous_counts=None,None
    while clock()<deadline:
        obs=nav.observe()
        captured=getattr(obs,'captured_monotonic',None)
        if (clock()>=deadline or nav.last is not obs or nav.focus_generation!=generation
                or getattr(obs,'focus_generation',None)!=generation or type(captured) not in (int,float)
                or not np.isfinite(captured)):
            return None
        counts=read_inventory(obs,gamertag)
        if counts is None:
            return None
        if (previous is not None and counts==previous_counts and obs is not previous
                and obs.frame is not previous.frame and captured>previous.captured_monotonic):
            nav.check()
            if identity()!=pinned:
                raise RuntimeError('Game changed while reading saved spin inventory')
            sync.require_verified(pinned);nav.check()
            if clock()>=deadline or nav.last is not obs or nav.focus_generation!=generation:
                return None
            runtime=read_json(Path(root)/'report_runtime.json')
            run=worker_run or (runtime.get('worker_run') if runtime.get('pid')==os.getpid() else None)
            nav.check()
            if identity()!=pinned:
                raise RuntimeError('Game changed before saving the observed spin inventory')
            if clock()>=deadline or nav.last is not obs or nav.focus_generation!=generation:
                return None
            observed_at=now()
            proof=dict(goal_id=goal_id,gamertag=gamertag,**counts,observed_at=observed_at,
                proof=PROOF,samples=2,game_identity=list(pinned),focus_generation=generation,
                worker_pid=os.getpid(),worker_run=run)
            if type(mission_rewards) is int and mission_rewards >= 0:
                proof['mission_rewards_at_observation']=mission_rewards
                previous_proof=read_json(Path(root)/'inventory_observed.json')
                previous_anchor=previous_proof.get('mission_rewards_at_observation')
                if (previous_proof.get('goal_id')==goal_id and previous_proof.get('proof')==PROOF
                        and previous_proof.get('samples')==2
                        and type(previous_proof.get('super_wheelspins')) is int
                        and type(previous_anchor) is int and 0<=previous_anchor<=mission_rewards):
                    estimate=previous_proof['super_wheelspins']+(mission_rewards-previous_anchor)
                    proof['hybrid_correction']={
                        'estimated_before_sync':estimate,
                        'actual':counts['super_wheelspins'],
                        'delta':counts['super_wheelspins']-estimate,
                        'verified_rewards_since_sync':mission_rewards-previous_anchor,
                        'at':observed_at,
                    }
            write_json(Path(root)/'inventory_observed.json',proof)
            return proof
        previous,previous_counts=obs,counts
        remaining=deadline-clock()
        if remaining>0:nav.pause(min(.04,remaining))
    return None


def apply_reward_events(record, mission_rewards):
    """Add verified mission rewards since the last native inventory reading.

    The mission counter is a high-water mark, so repeated reports and worker
    restarts cannot add the same reward twice. The next native reading replaces
    this estimate and records any correction.
    """
    if not isinstance(record,dict):
        return record
    result=dict(record)
    anchor=result.get('mission_rewards_at_observation')
    base=result.get('super_wheelspins')
    if (type(base) is int and base>=0 and type(anchor) is int and anchor>=0
            and type(mission_rewards) is int and mission_rewards>=anchor):
        added=mission_rewards-anchor
        result['actual_super_wheelspins_at_sync']=base
        result['verified_rewards_after_sync']=added
        result['super_wheelspins']=base+added
        result['estimated']=added>0
        result['source']='verified_rewards_after_home' if added else 'verified_my_horizon'
    else:
        result['actual_super_wheelspins_at_sync']=base if type(base) is int and base>=0 else None
        result['verified_rewards_after_sync']=0
        result['estimated']=False
    return result


def inventory_summary(data):
    """Normalize report inventory, including reward events after its Home sync."""
    source=data.get('inventory') or {}
    if not isinstance(source,dict):source={}
    fields={key:(source.get(key) if type(source.get(key)) is int and source[key]>=0 else None)
            for key in ('super_wheelspins','wheelspins')}
    stamp=source.get('observed_at')
    try:
        valid_stamp=isinstance(stamp,str) and datetime.fromisoformat(stamp).tzinfo is not None
    except ValueError:
        valid_stamp=False
    age=source.get('age_seconds')
    if type(age) not in (int,float) or not np.isfinite(age) or age<0:age=None
    current=(source.get('current_run') is True
             and source.get('source') in {'verified_my_horizon','verified_rewards_after_home'}
             and valid_stamp and age is not None and all(v is not None for v in fields.values()))
    added=source.get('verified_rewards_after_sync')
    if type(added) is not int or added<0:added=0
    actual=source.get('actual_super_wheelspins_at_sync')
    if type(actual) is not int or actual<0:actual=fields['super_wheelspins'] if added==0 else None
    correction=source.get('hybrid_correction')
    if not isinstance(correction,dict):correction=None
    return dict(**fields,observed_at=stamp if valid_stamp else None,age_seconds=age,
        current_run=bool(current),fresh=bool(current),source=source.get('source'),
        estimated=bool(current and source.get('estimated') is True),
        actual_super_wheelspins_at_sync=actual,verified_rewards_after_sync=added,
        mission_rewards_at_observation=source.get('mission_rewards_at_observation'),
        hybrid_correction=correction,
        field_observed_at=source.get('field_observed_at') or {},
        field_age_seconds=source.get('field_age_seconds') or {},
        reason='verified this run; last observed inventory' if current else 'awaiting current-run inventory read')
