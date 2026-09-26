from pathlib import Path
from test_wheelspin_bridge import bridge, args


def test_saved_policy_display_is_goal_bound():
    goal={'id':'sample','credit_stop_floor':{'goal_id':'sample','credits':1234567},'cleanup_policy':'final_only'}
    assert bridge.credit_policy_fields(goal)=={'goal_credit_floor':1234567,'goal_cleanup_policy':'final_only'}
    goal['credit_stop_floor']['goal_id']='other'
    assert bridge.credit_policy_fields(goal)['goal_credit_floor']==''
    assert bridge.credit_policy_fields({})['goal_credit_floor']==''


def test_blank_ui_defaults_preserve_policy_by_omitting_overrides():
    config=bridge.configuration(args(mode=bridge.GOAL_MODE,target='10'),{}, {})
    assert config['credit_floor'] is None
    assert config['cleanup_policy'] is None
    config=bridge.configuration(args(mode=bridge.GOAL_MODE,target='10',credit_floor=1234567,cleanup_policy='final_only'),{}, {})
    assert (config['credit_floor'],config['cleanup_policy'])==(1234567,'final_only')


def test_panel_cli_seam_uses_only_explicit_inputs_and_locks_running_controls():
    text=Path('Forza-Horizon-6-Wheelspin-Macro-main/Modules/LocalPanel.ahk').read_text(encoding='utf-8')
    method=text.split('    CreditPolicyArgs() {',1)[1].split('    Poll(*) {',1)[0]
    assert 'if floor != ""' in method and ' --credit-floor ' in method
    assert 'if this.cleanupPolicy.Value = 2' in method and ' --cleanup-policy final_only' in method
    assert 'if this.mode.Text != "Earn saved Super Wheelspins"' in method
    assert 'command .= this.CreditPolicyArgs()' in text
    assert 'this.creditFloor.Enabled := !busy' in text
    assert 'this.cleanupPolicy.Enabled := !busy' in text
    assert 'Blank preserves this setting on resume.' in text
