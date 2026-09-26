from copy import deepcopy
from datetime import datetime, timezone

import pytest

from fh6.inventory import PROOF
from fh6.panel_inventory import inventory_labels


def records():
    return [dict(goal_id='goal',gamertag='Player',super_wheelspins=1812,wheelspins=337,
                 observed_at='2026-09-26T06:40:00+00:00',proof=PROOF,samples=2,
                 worker_pid=10,worker_run='old'),
            dict(id='goal',credit_account='player'),dict(gamertag='PLAYER'),
            dict(pid=20,worker_run='new',worker_started_at='2026-09-26T06:41:00+00:00')]


def labels(data):
    return inventory_labels(*data,20,now=datetime(2026,9,26,7,tzinfo=timezone.utc))


def test_previous_worker_keeps_last_verified_counts_and_timestamp():
    data=records()
    before=deepcopy(data)
    result=labels(data)
    assert result['inventory_line']=='LAST VERIFIED  1,812 SW  |  337 WS'
    assert data[0]['observed_at'] in result['inventory_read']
    assert 'current balance not reread' in result['inventory_read']
    assert data==before


def test_current_worker_keeps_strict_existing_label():
    data=records()
    data[0].update(worker_pid=20,worker_run='new',observed_at='2026-09-26T06:42:00+00:00')
    result=labels(data)
    assert result['inventory_line']=='SAVED  1,812 SW  |  337 WS'
    assert result['inventory_read']=='Read 2026-09-26T06:42:00+00:00'


@pytest.mark.parametrize('index,key,value',[
    (0,'goal_id','other'),(0,'gamertag','other'),(1,'credit_account','other'),
    (1,'credit_account',''),(2,'gamertag','other'),(0,'proof','estimated'),
    (0,'samples',1),(0,'wheelspins',-1),(0,'super_wheelspins',True),
    (0,'observed_at','2026-09-26T08:00:00+00:00'),
    (0,'observed_at','2026-09-26T06:40:00'),(0,'observed_at','bad')])
def test_unbound_unverified_or_invalid_proof_is_not_displayed(index,key,value):
    data=records()
    data[index][key]=value
    assert 'awaiting live game read' in labels(data)['inventory_line']


def test_worker_timestamp_before_start_never_gets_current_label():
    data=records()
    data[0].update(worker_pid=20,worker_run='new')
    assert labels(data)['inventory_line'].startswith('LAST VERIFIED')


def test_missing_proof_is_display_placeholder():
    data=records()
    data[0]={}
    assert 'awaiting live game read' in labels(data)['inventory_line']
