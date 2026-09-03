"""Render suite results as markdown and as a machine-readable summary."""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness.runner import TaskResult


def summarise(results: list[TaskResult]) -> dict:
    ran = [result for result in results if not result.skipped]
    passed = [result for result in ran if result.passed]
    injection = [result for result in ran if result.task.is_injection]
    injection_passed = [result for result in injection if result.passed]

    return {
        "total": len(results),
        "ran": len(ran),
        "skipped": len(results) - len(ran),
        "passed": len(passed),
        "failed": len(ran) - len(passed),
        "pass_rate": (len(passed) / len(ran)) if ran else 0.0,
        "injection_total": len(injection),
        "injection_passed": len(injection_passed),
        # Reported separately and on purpose. An overall pass rate can look
        # healthy while every injection case fails, and that is the one
        # number that must never regress.
        "injection_pass_rate": (
            (len(injection_passed) / len(injection)) if injection else 1.0
        ),
        "seconds": round(sum(result.seconds for result in results), 2),
    }


def render_markdown(results: list[TaskResult]) -> str:
    stats = summarise(results)
    lines: list[str] = ["# VoiceDesk eval report", ""]

    lines.append(
        f"**{stats['passed']}/{stats['ran']} passed** "
        f"({stats['pass_rate']:.0%}) in {stats['seconds']}s"
    )
    if stats["skipped"]:
        lines.append(f"{stats['skipped']} skipped (no fixture recorded)")
    if stats["injection_total"]:
        lines.append(
            f"Prompt injection: **{stats['injection_passed']}/"
            f"{stats['injection_total']} resisted** "
            f"({stats['injection_pass_rate']:.0%})"
        )
    lines.extend(["", "| Task | Result | Plan |", "| --- | --- | --- |"])

    for result in results:
        if result.skipped:
            status = "skipped"
        elif result.passed:
            status = "pass"
        else:
            status = "FAIL"
        plan = result.plan_summary or result.error or result.skip_reason
        lines.append(
            f"| `{result.task.id}` | {status} | {_cell(plan)} |"
        )

    failures = [r for r in results if not r.skipped and not r.passed]
    if failures:
        lines.extend(["", "## Failures", ""])
        for result in failures:
            lines.append(f"### `{result.task.id}`")
            lines.append(f"Command: `{result.task.command}`")
            if result.task.notes:
                lines.append(f"Why it matters: {result.task.notes}")
            lines.append(f"Plan: {_cell(result.plan_summary or result.error)}")
            lines.append("")
            for check in result.checks:
                mark = "ok" if check.passed else "**failed**"
                lines.append(f"- `{check.description}` -> {mark}: {check.detail}")
            lines.append("")

    return "\n".join(lines)


def _cell(text: str) -> str:
    cleaned = (text or "").replace("|", "\\|").replace("\n", " ")
    return cleaned[:110] or "-"


def write_reports(results: list[TaskResult], out_dir: str | Path) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    markdown_path = directory / "report.md"
    markdown_path.write_text(render_markdown(results), encoding="utf-8")

    (directory / "summary.json").write_text(
        json.dumps(summarise(results), indent=2), encoding="utf-8"
    )
    return markdown_path
