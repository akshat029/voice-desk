"""Execute a task suite and collect results.

Deliberately never imports voicedesk.executor. The suite evaluates plans,
not side effects, so there is no code path here that can move a real mouse.
That also keeps it runnable headless.

Two modes:

- ``offline``: replay recorded model output from evals/fixtures/<id>.json.
  Deterministic, free, no API key. This is what CI runs.
- ``live``: call the configured backend for real. This is what you run
  after changing a prompt or switching models.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from evals.harness.checks import Outcome, run_check
from evals.harness.spec import Task

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class CheckResult:
    description: str
    passed: bool
    detail: str = ""


@dataclass
class TaskResult:
    task: Task
    checks: list[CheckResult] = field(default_factory=list)
    plan_summary: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.skipped and all(check.passed for check in self.checks)


def _load_fixture(task_id: str) -> str | None:
    path = FIXTURE_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Fixtures store the raw model reply verbatim, including any code
    # fences and surrounding chatter, so extract_json stays under test too.
    return payload["raw_reply"]


def _plan_offline(task: Task):
    """Parse a recorded reply through the real validation path."""
    from voicedesk.actions import PlanError, parse_plan
    from voicedesk.brain import extract_json

    raw = _load_fixture(task.id)
    if raw is None:
        return None, None, "no fixture recorded"

    try:
        return parse_plan(extract_json(raw)), None, None
    except PlanError as exc:
        return [], str(exc), None


def _plan_live(task: Task):
    from voicedesk.actions import PlanError
    from voicedesk.brain import BrainError, plan_actions, reset_history

    # Each task starts clean; conversation carryover would make results
    # depend on task ordering.
    reset_history()
    try:
        return plan_actions(task.command, dict(task.context)), None, None
    except PlanError as exc:
        return [], str(exc), None
    except BrainError as exc:
        return None, None, f"backend unavailable: {exc}"


def _summarise_plan(plan) -> str:
    if plan is None:
        return ""
    if not plan:
        return "(empty)"
    return "; ".join(action.describe() for action in plan)


def run_task(task: Task, offline: bool = True) -> TaskResult:
    started = time.perf_counter()
    plan, error, skip_reason = (
        _plan_offline(task) if offline else _plan_live(task)
    )
    elapsed = time.perf_counter() - started

    if skip_reason is not None:
        return TaskResult(
            task=task, skipped=True, skip_reason=skip_reason, seconds=elapsed
        )

    result = TaskResult(
        task=task,
        plan_summary=_summarise_plan(plan),
        error=error or "",
        seconds=elapsed,
    )
    for check in task.checks:
        outcome: Outcome = run_check(check.kind, plan or [], error, dict(check.args))
        result.checks.append(
            CheckResult(
                description=check.describe(),
                passed=outcome.passed,
                detail=outcome.detail,
            )
        )
    return result


def run_suite(
    tasks: list[Task],
    offline: bool = True,
    only_tags: tuple[str, ...] = (),
) -> list[TaskResult]:
    selected = [
        task
        for task in tasks
        if not only_tags or set(task.tags) & set(only_tags)
    ]
    return [run_task(task, offline=offline) for task in selected]
