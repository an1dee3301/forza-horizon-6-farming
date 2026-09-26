from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from fh6.production import Production


def make_job():
    job=Production.__new__(Production)
    goal=NS(data=dict(id='example-goal',phase='garage_cleanup',rewards=8,credit_account='ExampleDriver'))
    history=[]
    def save(**kw):
        goal.data.update(kw);history.append(dict(goal.data))
    goal.save=save;job.goal=goal
    job.nav=Mock();job.nav.account_observer=NS(gamertag='ExampleDriver')
    job.terminal_cleaner=Mock(return_value=8)
    job.boundary=lambda name,action:action()
    job.emit=Mock();job.progress=Mock()
    return job,history


def proof():
    return dict(goal_id='example-goal',gamertag='ExampleDriver',proof='two_fresh_my_horizon_frames',samples=2,
                observed_at='2026-09-26T12:00:00Z',super_wheelspins=123,wheelspins=45)


def test_completion_is_durable_before_fresh_observation(monkeypatch):
    job,history=make_job();observations=[]
    def refresh(nav,goal,**kw):
        assert history[-2]['phase']=='complete'
        assert history[-1]['final_inventory']['status']=='attempting'
        assert kw['interval']==0 and kw['stay_pause'] is True
        observations.append(kw)
        return proof()
    monkeypatch.setattr('fh6.inventory_route.refresh_inventory',refresh)
    job.cleanup_credit_limit()
    assert job.goal.data['final_inventory']==dict(status='verified',proof=proof())
    assert job.goal.data['phase']=='complete'
    job.cleanup_credit_limit();job.observe_final_inventory()
    job.terminal_cleaner.assert_called_once()
    assert len(observations)==1


@pytest.mark.parametrize('failure',['exception','wrong_account','missing_samples','bad_counts'])
def test_optional_failure_never_reopens_or_repeats_cleanup(monkeypatch,failure):
    job,_=make_job()
    def refresh(*args,**kwargs):
        if failure=='exception':raise RuntimeError('route unavailable')
        p=proof()
        if failure=='wrong_account':p['gamertag']='Other'
        if failure=='missing_samples':p['samples']=1
        if failure=='bad_counts':p['wheelspins']=-1
        return p
    monkeypatch.setattr('fh6.inventory_route.refresh_inventory',refresh)
    job.cleanup_credit_limit();job.cleanup_credit_limit()
    assert job.goal.data['phase']=='complete'
    assert job.goal.data['final_inventory']['status']=='unavailable'
    job.terminal_cleaner.assert_called_once()


def test_interrupted_attempt_and_precompletion_never_route(monkeypatch):
    job,_=make_job();refresh=Mock()
    monkeypatch.setattr('fh6.inventory_route.refresh_inventory',refresh)
    job.observe_final_inventory()
    job.goal.save(phase='complete',final_inventory={'status':'attempting'})
    job.observe_final_inventory()
    refresh.assert_not_called()
