"""Regression tests for the plan validator.

Each test here corresponds to a defect that shipped.
"""

import pytest

from voicedesk.actions import PlanError, Risk, highest_risk, parse_plan


def test_click_requires_coordinates():
    # pyautogui.click(x=None, y=None) clicks wherever the cursor already
    # is, so a coordinate-less click must never reach the executor.
    with pytest.raises(PlanError):
        parse_plan([{"action": "click"}])
    with pytest.raises(PlanError):
        parse_plan([{"action": "click", "x": 10}])
    with pytest.raises(PlanError):
        parse_plan([{"action": "click", "x": None, "y": None}])


def test_modifier_press_is_promoted_to_hotkey():
    # The old _press_many pressed keys sequentially, so a "copy this"
    # command typed the letter c instead of copying.
    (action,) = parse_plan([{"action": "press", "keys": ["ctrl", "c"]}])
    assert action.action == "hotkey"
    assert action.keys == ["ctrl", "c"]


def test_single_key_press_stays_a_press():
    (action,) = parse_plan([{"action": "press", "keys": ["enter"]}])
    assert action.action == "press"


def test_sequential_press_without_modifier_is_preserved():
    (action,) = parse_plan([{"action": "press", "keys": ["h", "i"]}])
    assert action.action == "press"


def test_key_aliases_are_canonicalised():
    (action,) = parse_plan([{"action": "hotkey", "keys": ["Control", "Return"]}])
    assert action.keys == ["ctrl", "enter"]


def test_string_keys_are_accepted():
    (action,) = parse_plan([{"action": "press", "keys": "escape"}])
    assert action.keys == ["escape"]


@pytest.mark.parametrize(
    "keys",
    [["alt", "f4"], ["ctrl", "w"], ["ctrl", "shift", "delete"], ["delete"]],
)
def test_destructive_hotkeys_are_flagged(keys):
    (action,) = parse_plan([{"action": "hotkey", "keys": keys}])
    assert action.risk is Risk.DESTRUCTIVE


def test_copy_is_not_destructive():
    (action,) = parse_plan([{"action": "hotkey", "keys": ["ctrl", "c"]}])
    assert action.risk is Risk.WRITE


def test_open_app_is_launch_risk():
    (action,) = parse_plan([{"action": "open_app", "name": "chrome"}])
    assert action.risk is Risk.LAUNCH


def test_speak_and_wait_are_read_only():
    actions = parse_plan(
        [{"action": "speak", "text": "hi"}, {"action": "wait", "seconds": 1}]
    )
    assert highest_risk(actions) is Risk.READ


def test_unknown_action_is_rejected():
    # A model that invents run_shell should be refused, not executed.
    with pytest.raises(PlanError):
        parse_plan([{"action": "run_shell", "cmd": "rm -rf /"}])


def test_unexpected_field_is_rejected():
    with pytest.raises(PlanError):
        parse_plan([{"action": "click", "x": 1, "y": 2, "button": "middle"}])


def test_wait_is_bounded():
    with pytest.raises(PlanError):
        parse_plan([{"action": "wait", "seconds": 6000}])


def test_type_rejects_empty_text():
    with pytest.raises(PlanError):
        parse_plan([{"action": "type", "text": ""}])


def test_plan_must_be_a_list():
    with pytest.raises(PlanError):
        parse_plan("click the button")


def test_wrapped_actions_key_is_unwrapped():
    # Models asked for JSON often wrap the array in an object.
    actions = parse_plan({"actions": [{"action": "speak", "text": "hi"}]})
    assert len(actions) == 1


def test_highest_risk_picks_the_worst_step():
    actions = parse_plan(
        [
            {"action": "speak", "text": "ok"},
            {"action": "type", "text": "hello"},
            {"action": "hotkey", "keys": ["alt", "f4"]},
        ]
    )
    assert highest_risk(actions) is Risk.DESTRUCTIVE


def test_empty_plan_is_read_risk():
    assert highest_risk([]) is Risk.READ
