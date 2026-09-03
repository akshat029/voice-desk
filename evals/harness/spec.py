"""Task and check definitions.

Tasks live in a JSONL file: one JSON object per line, blank lines and
lines starting with # ignored. JSONL rather than YAML so the harness adds
no dependency, and one-object-per-line keeps diffs readable when tasks are
added.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class SuiteError(Exception):
    """The task file itself is malformed."""


@dataclass(frozen=True)
class Check:
    kind: str
    args: dict = field(default_factory=dict)

    def describe(self) -> str:
        if not self.args:
            return self.kind
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.args.items()))
        return f"{self.kind}({rendered})"


@dataclass(frozen=True)
class Task:
    id: str
    command: str
    checks: tuple[Check, ...]
    context: dict = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    notes: str = ""

    @property
    def is_injection(self) -> bool:
        return "injection" in self.tags


def _parse_task(raw: dict, line_no: int) -> Task:
    for required in ("id", "command", "checks"):
        if required not in raw:
            raise SuiteError(f"line {line_no}: missing required key {required!r}")

    checks = []
    for entry in raw["checks"]:
        if not isinstance(entry, dict) or "kind" not in entry:
            raise SuiteError(f"line {line_no}: each check needs a 'kind'")
        kind = entry.pop("kind")
        checks.append(Check(kind=kind, args=entry))

    if not checks:
        raise SuiteError(f"line {line_no}: task {raw['id']!r} has no checks")

    return Task(
        id=str(raw["id"]),
        command=str(raw["command"]),
        checks=tuple(checks),
        context=dict(raw.get("context") or {}),
        tags=tuple(raw.get("tags") or ()),
        notes=str(raw.get("notes", "")),
    )


def load_tasks(path: str | Path) -> list[Task]:
    text = Path(path).read_text(encoding="utf-8")
    tasks: list[Task] = []
    seen: set[str] = set()

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SuiteError(f"line {line_no}: invalid JSON ({exc.msg})") from exc

        task = _parse_task(raw, line_no)
        if task.id in seen:
            raise SuiteError(f"line {line_no}: duplicate task id {task.id!r}")
        seen.add(task.id)
        tasks.append(task)

    if not tasks:
        raise SuiteError(f"no tasks found in {path}")
    return tasks
