"""Confirmation parsing and risk escalation."""

import pytest

from voicedesk.actions import Risk, parse_plan
from voicedesk.safety import effective_risk, parse_confirmation


@pytest.mark.parametrize(
    "reply",
    ["yes", "Yes please", "yeah go ahead", "sure", "ok", "okay, proceed", "confirm"],
)
def test_affirmative_replies_approve(reply):
    assert parse_confirmation(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        # This is the one that mattered: the old substring check found
        # "do it" inside "don't do it" and approved the action.
        "no, don't do it",
        "no",
        "nope",
        "stop",
        "cancel that",
        "actually don't",
        "wait, no",
        "never mind",
    ],
)
def test_negative_replies_refuse(reply):
    assert parse_confirmation(reply) is False


@pytest.mark.parametrize("reply", ["", "   ", "hmm", "what", "the weather is nice"])
def test_ambiguous_replies_refuse(reply):
    # Silence or unrelated speech must never count as consent.
    assert parse_confirmation(reply) is False


@pytest.mark.parametrize("reply", ["I spoke to her", "take a look", "the vase broke"])
def test_substrings_of_ok_do_not_approve(reply):
    # "ok" used to match inside spoke / look / broke.
    assert parse_confirmation(reply) is False


def test_typing_into_a_shell_is_destructive():
    (action,) = parse_plan([{"action": "type", "text": "rm -rf ~"}])
    assert effective_risk(action, "Windows PowerShell") is Risk.DESTRUCTIVE


def test_typing_into_an_editor_is_not_destructive():
    (action,) = parse_plan([{"action": "type", "text": "hello"}])
    assert effective_risk(action, "Untitled - Notepad") is Risk.WRITE


def test_risk_without_window_context_falls_back():
    (action,) = parse_plan([{"action": "type", "text": "hello"}])
    assert effective_risk(action, "") is Risk.WRITE
