from threading import Event
import re

import pytest

from fh6.wheelspin import (WheelspinPolicy, guarded_action,
                           match_dialog_reward, protected_keep_match)
from fh6.wheelspin_catalog import lamborghini_candidate


def test_unknown_car_fails_closed():
    decision = WheelspinPolicy().decide(dict(reward_type="CAR", duplicate=True,
        protected=None, decision_confidence=.4))
    assert decision.action == "UNKNOWN_DECISION"
    assert decision.send_input is False


def test_protected_duplicate_is_kept_and_other_duplicate_is_sold():
    policy = WheelspinPolicy()
    keep = policy.decide(dict(reward_type="CAR", duplicate=True, protected=True,
                              decision_confidence=.99))
    sell = policy.decide(dict(reward_type="CAR", duplicate=True, protected=False,
                              decision_confidence=.99))
    assert keep.action == "KEEP"
    assert sell.action == "SELL"


def test_focus_loss_and_f7_prevent_input():
    sent = []
    running = Event()
    running.set()
    with pytest.raises(RuntimeError, match="focus"):
        guarded_action(running, lambda: False, lambda: sent.append("sell"))
    assert sent == []
    running.clear()
    with pytest.raises(RuntimeError, match="F7"):
        guarded_action(running, lambda: True, lambda: sent.append("sell"))
    assert sent == []


@pytest.mark.parametrize("name", [
    "M-B CLK-GTR", "Mercedes-Benz AMG CLK GTR", "Koenigsegg One:1",
    "Hennessey Venom GT", "Rimac Nevera", "Apollo IE",
    "Ferrari 599XX Evo", "Lamborghini Sian", "Ferrari LaFerrari",
])
def test_every_user_keep_alias_fails_closed_to_keep(name):
    assert protected_keep_match(name)


def test_unlisted_car_does_not_match_keep_aliases():
    assert not protected_keep_match("1979 Chevrolet Camaro Z28")


@pytest.mark.parametrize("name", [
    "Sesto Elemento", "Essenza SCV12", "Countach LPI 800-4",
    "Huracan Tecnica", "Huracén Tecnica", "Centenario LP 770-4",
])
def test_lamborghini_model_only_dialogs_are_protected(name):
    assert lamborghini_candidate(name)


def test_multiple_duplicate_dialogs_are_matched_by_identity_not_slot_order():
    rows = [
        {"reward_id": 1, "slot_index": 1, "raw_ocr": "1972 RELIANT Supervan III"},
        {"reward_id": 2, "slot_index": 3, "raw_ocr": "1995 MITSUBISHI Eclipse GSX"},
    ]
    eclipse, confidence = match_dialog_reward("ECLIPSE GSX", rows)
    reliant, confidence2 = match_dialog_reward("RELIANT SUPERVAN", rows)
    assert eclipse["reward_id"] == 2 and confidence == 1.0
    assert reliant["reward_id"] == 1 and confidence2 == 1.0


def test_ambiguous_duplicate_identity_blocks_destructive_action():
    rows = [
        {"reward_id": 1, "raw_ocr": "FORD MUSTANG"},
        {"reward_id": 2, "raw_ocr": "FORD MUSTANG"},
    ]
    assert match_dialog_reward("FORD MUSTANG", rows) == (None, 0.0)


def test_last_unresolved_car_is_unambiguous_after_other_duplicate_is_done():
    rows = [{"reward_id": 927, "reward_type": "CAR",
             "raw_ocr": "2016 CIS-V Sedan"}]
    result, confidence = match_dialog_reward("CADDY CTS V 16", rows)
    assert result["reward_id"] == 927
    assert confidence == 1.0


def test_single_other_reward_can_be_bound_by_native_duplicate_dialog():
    rows = [{"reward_id": 1012, "reward_type": "OTHER",
             "raw_ocr": "hand Cherokee Trackhawk"}]
    result, confidence = match_dialog_reward("Jeep Trackhawk", rows)
    assert result["reward_id"] == 1012
    assert confidence == 1.0


def test_numeric_other_slot_is_not_a_duplicate_car_candidate():
    unresolved = [
        {"reward_id": 1, "reward_type": "OTHER", "raw_ocr": "GTO"},
        {"reward_id": 2, "reward_type": "OTHER", "raw_ocr": "20,000"},
    ]
    numeric = re.compile(r"\s*(?:CR\s*)?[0-9O][0-9O,.\s]*\s*(?:CR)?\s*")
    candidates = [row for row in unresolved if not numeric.fullmatch(row["raw_ocr"].upper())]
    result, confidence = match_dialog_reward("Mitsubishi GTO", candidates)
    assert result["reward_id"] == 1 and confidence == 1.0


def test_other_car_can_beat_incorrect_nominal_car_by_native_identity():
    rows = [
        {"reward_id": 1, "reward_type": "OTHER",
         "raw_ocr": "Grand Cherokee Trackhawk"},
        {"reward_id": 2, "reward_type": "CAR",
         "raw_ocr": "2025 CHEVROLET Corvette ZR-1"},
    ]
    result, confidence = match_dialog_reward("Jeep Trackhawk", rows)
    assert result["reward_id"] == 1 and confidence == 1.0
