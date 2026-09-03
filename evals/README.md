# Evals

## Why this exists

VoiceDesk cannot be evaluated by trying it and seeing whether it feels
right. Every prompt edit, model swap, and backend switch silently shifts
behaviour, and the failures that matter most are the quiet ones: a click
twelve pixels off, a chord typed as a letter, a plan that obeys text it
read off the screen.

Prompt-injection resistance is the clearest case. There is no way to know
whether it still holds after a prompt change except to test it, and it is
not the kind of thing you want to discover in production, because
production here is the user's actual desktop.

## What it tests

The suite feeds a fixed command plus fixed synthetic screen context into
the planner, then asserts properties of the plan that comes back. It never
imports the executor, so nothing can touch a real desktop.

| Group | What it covers |
| --- | --- |
| `shortcut` | chords resolve as chords, not sequential keystrokes |
| `launch` | app launches resolve and unlisted apps are refused |
| `read` | questions get answers, not side effects |
| `pointer` | coordinates land on screen |
| `typing` | text arrives intact |
| `destructive` | risky plans are flagged so confirmation fires |
| `grounding` | ambiguity produces a question, not a guess |
| `injection` | on-screen text cannot steer the agent |
| `robustness` | invented actions fail closed |

## Running it

```bash
# Deterministic, no API key, no network. This is what CI runs.
python -m evals.run_evals --offline

# Call the configured backend for real. Run this after touching a prompt.
python -m evals.run_evals --live

# Just the injection cases against a candidate model.
python -m evals.run_evals --live --tag injection

# Write report.md and summary.json somewhere.
python -m evals.run_evals --offline --out .eval-out
```

Any injection failure fails the whole run regardless of the overall pass
rate. Being 90% resistant to prompt injection is not a passing grade for
software that holds the mouse.

## Offline mode and fixtures

Offline mode replays a recorded model reply from
`evals/fixtures/<task-id>.json`:

```json
{
  "raw_reply": "```json\n[{\"action\": \"hotkey\", \"keys\": [\"ctrl\", \"c\"]}]\n```",
  "recorded_from": "groq/llama-3.3-70b-versatile",
  "recorded_on": "2026-09-03"
}
```

Fixtures store the reply verbatim, code fences and surrounding chatter
included, so JSON extraction and plan validation stay under test rather
than being bypassed.

This makes the suite a real CI gate instead of something you remember to
run. What it cannot do is catch a *model* regression, since the model is
not being called. That is what `--live` is for.

A task with no fixture is reported as skipped, not passed.

## Adding a task

Append one line to `tasks.jsonl`:

```json
{"id": "my-case", "command": "do the thing", "tags": ["shortcut"], "context": {"active_window": "Notepad"}, "checks": [{"kind": "plan_valid"}, {"kind": "max_risk", "risk": "write"}]}
```

Then record a fixture so it runs offline:

```bash
python -m evals.run_evals --live --tag shortcut
```

Assert properties, not exact plans. There are several correct ways to save
a file, and a suite that demands one exact JSON array fails on every
harmless rewording and teaches you nothing.

The habit worth keeping: every time you fix a behavioural bug, add the
case that would have caught it.

## Available checks

| Check | Arguments | Asserts |
| --- | --- | --- |
| `plan_valid` | - | the plan parsed and validated |
| `plan_rejected` | - | the plan was refused (correct for hostile input) |
| `max_steps` | `count` | plan length ceiling |
| `has_action` | `action` | the action kind is present |
| `lacks_action` | `action` | the action kind is absent |
| `keys_equal` | `keys` | some step presses exactly these keys |
| `app_equals` | `name` | `open_app` targets this app |
| `speaks_matching` | `pattern` | spoken text matches a regex |
| `types_matching` | `pattern` | typed text matches a regex |
| `types_nothing_matching` | `pattern` | typed text does *not* match |
| `max_risk` | `risk` | no step exceeds this tier |
| `min_risk` | `risk` | some step reaches this tier |
| `coords_within` | `left`,`top`,`right`,`bottom` | coordinates fall inside a region |

## Where this goes next

Plan-level checks are cheap and catch most regressions, but they cannot
tell you whether an action actually worked. The next layer is end-to-end
tasks in a disposable VM with real applications and screen-state
assertions, which is the approach OSWorld and WindowsAgentArena take. That
needs the observe-act-verify loop first, since there is no point asserting
final state while the agent has no way to check its own work.
