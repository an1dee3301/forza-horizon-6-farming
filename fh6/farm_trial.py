"""Durable, bounded Mini V2 trial. No advertised yield authorizes a purchase."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .analytics import read, save
from .profiles import load_profile

MINI = '169055890'
MEGA = '155439962'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def seconds(start, end):
    try:
        a,b = datetime.fromisoformat(start),datetime.fromisoformat(end)
        if a.tzinfo is None:a=a.astimezone()
        if b.tzinfo is None:b=b.astimezone()
        return max(0,(b-a).total_seconds())
    except (ValueError,TypeError):return 0


def rate(rows):
    elapsed=sum(r.get('wall_seconds',0) for r in rows)
    return sum(r.get('retained_sp',0) for r in rows)*3600/elapsed if elapsed>0 else None


def optimization_metrics(rows):
    """Compare recorded routes without changing the whole-trial keep decision.

    Runs predating route instrumentation remain legacy. Full run wall time keeps
    searches, retries, restarts and loading in the denominator; overhead is only
    measured when a plausible native drive duration was recorded as well.
    """
    groups={}
    latest=None
    for row in rows:
        version=row.get('optimization_version') or 'legacy'
        groups.setdefault(version,[]).append(row)
        if version!='legacy':latest=version
    versions={}
    for version,samples in groups.items():
        walls=[r['wall_seconds'] for r in samples if r.get('wall_seconds',0)>0]
        overhead=[r['wall_seconds']-r['drive_seconds'] for r in samples
                  if isinstance(r.get('drive_seconds'),(int,float))
                  and 0<r['drive_seconds']<=r.get('wall_seconds',0)]
        versions[version]=dict(completed_runs=len(samples),
            retained_sp=sum(r.get('retained_sp',0) for r in samples),
            wall_seconds=sum(r.get('wall_seconds',0) for r in samples),
            retained_sp_hour=rate(samples),
            median_wall_seconds=median(walls) if walls else None,
            median_overhead_seconds=median(overhead) if overhead else None,
            wall_timing_samples=len(walls),overhead_timing_samples=len(overhead))
    before=versions.get('legacy',{}).get('retained_sp_hour')
    after=versions.get(latest,{}).get('retained_sp_hour')
    return dict(baseline_version='legacy',latest_version=latest,versions=versions,
                retained_sp_hour_gain_percent=(after/before-1)*100
                if before and after is not None else None)


class FarmTrial:
    def __init__(self, root):
        self.root=Path(root)
        self.path=self.root/'farm_trial.json'
        self.data=read(self.path)

    def persist(self):
        save(self.path,self.data)

    def arm(self, goal, analytics):
        if self.data.get('status') in {'pending','active'}:
            return self.data
        farms=[]
        for r in analytics.get('farms',[])[-10:]:
            elapsed=seconds(r.get('started_at'),r.get('ended_at'))
            if elapsed>0 and r.get('share_code',MEGA)==MEGA:
                farms.append(dict(id=r['id'],retained_sp=r.get('gained_sp',0),wall_seconds=elapsed))
        self.data=dict(goal_id=goal['id'],status='pending',candidate=MINI,baseline_code=MEGA,
            requested_at=stamp(),reward_limit=100,minimum_gain_percent=5,
            baseline_farms=farms,baseline_sp_hour=rate(farms),runs=[])
        self.persist();return self.data

    def prepare(self, goal, challenge):
        d=self.data
        if not d or d.get('goal_id')!=goal['id']:return
        # Finish the pinned run before applying a different share code.
        unlaunched=(challenge.data.get('phase') in {'prepare','search'} and not challenge.data.get('launch_attempts'))
        if challenge.data and challenge.data.get('phase')!='complete' and not unlaunched:return
        if d['status']=='pending':
            d.update(status='active',started_at=stamp(),start_rewards=goal['rewards'],
                     start_active_seconds=goal.get('active_seconds',0),start_sp=goal.get('last_sp'))
            self.persist()
        profile=load_profile()
        challenge.profile=(replace(profile,name='Mini Farm V2',share_code=MINI,duration_seconds=300,
                                    source='User-provided Mini V2 share code; live trial')
                           if d['status'] in {'active','kept'} else profile)
        if unlaunched:
            challenge.data.pop('refill_plan',None)
            challenge.save(share_code=challenge.profile.share_code)

    def started(self, identifier, share_code):
        if self.data.get('status')!='active' or share_code!=MINI:return
        if (self.data.get('open_run') or {}).get('id')!=identifier:
            self.data['open_run']=dict(id=identifier,started_at=stamp())
            from .farm_route import OPTIMIZATION_VERSION
            rollout=read(self.root/'farm_optimization.json')
            if (rollout.get('goal_id')==self.data.get('goal_id')
                    and rollout.get('optimization_version')==OPTIMIZATION_VERSION):
                self.data['open_run']['optimization_version']=OPTIMIZATION_VERSION
                self.data['optimization_rollout']=rollout
            self.persist()

    def completed(self, challenge):
        d=self.data;r=challenge.data
        if d.get('status')!='active' or r.get('share_code')!=MINI:return
        if any(x['id']==r['id'] for x in d['runs']):return
        opened=d.get('open_run') or {}
        opened=opened if opened.get('id')==r['id'] else {}
        started=opened.get('started_at')
        retained=max(0,r.get('after_sp',0)-r.get('before_sp',0))
        recorded=dict(id=r['id'],retained_sp=retained,
            wall_seconds=seconds(started,stamp()),drive_seconds=r.get('drive_seconds'),
            exit_reason=r.get('exit_reason'),before_sp=r.get('before_sp'),after_sp=r.get('after_sp'))
        if opened.get('optimization_version'):
            recorded['optimization_version']=opened['optimization_version']
        d['runs'].append(recorded)
        d.pop('open_run',None)
        if retained==0:d.update(status='reverted',reason='Mini retained no SP; return to Mega V6',decided_at=stamp())
        self.persist()

    def evaluate(self, goal):
        d=self.data
        if d.get('status')!='active' or d.get('goal_id')!=goal['id']:return
        earned=goal['rewards']-d['start_rewards']
        if earned<d['reward_limit']:return
        candidate,baseline=rate(d['runs']),d.get('baseline_sp_hour')
        gain=(candidate/baseline-1)*100 if candidate and baseline else None
        wall=seconds(d['started_at'],stamp())
        active=goal.get('active_seconds',0)-d['start_active_seconds']
        keep=bool(gain is not None and gain>=d['minimum_gain_percent'] and len(d['runs'])>=3)
        d.update(status='kept' if keep else 'reverted',decided_at=stamp(),end_rewards=goal['rewards'],
            end_sp=goal.get('last_sp'),earned=earned,trial_sp_hour=candidate,gain_percent=gain,
            actual_sw_wall_hour=earned*3600/wall if wall else None,
            actual_sw_active_hour=earned*3600/active if active>0 else None,
            optimization_comparison=optimization_metrics(d['runs']),
            reason='At least 5% higher retained SP/hour including run overhead' if keep else
                   f"No demonstrated 5% gain after {d['reward_limit']} new SW; return to Mega V6")
        self.persist()
