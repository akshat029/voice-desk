"""Command line entry point for the eval suite.

    python -m evals.run_evals --offline
    python -m evals.run_evals --live
    python -m evals.run_evals --live --tag injection
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.harness.report import render_markdown, summarise, write_reports
from evals.harness.runner import run_suite
from evals.harness.spec import SuiteError, load_tasks

DEFAULT_TASKS = Path(__file__).resolve().parent / "tasks.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the VoiceDesk eval suite.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline",
        action="store_true",
        help="replay recorded fixtures; no API key or network needed",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="call the configured LLM backend for real",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="only run tasks with this tag; repeatable",
    )
    parser.add_argument("--out", default=None, help="directory for report files")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=None,
        help="exit non-zero below this overall pass rate",
    )
    args = parser.parse_args(argv)

    offline = not args.live

    try:
        tasks = load_tasks(args.tasks)
    except (SuiteError, OSError) as exc:
        print(f"Could not load tasks: {exc}", file=sys.stderr)
        return 2

    results = run_suite(tasks, offline=offline, only_tags=tuple(args.tag))
    print(render_markdown(results))

    if args.out:
        path = write_reports(results, args.out)
        print(f"\nReport written to {path}", file=sys.stderr)

    stats = summarise(results)

    # Injection failures always fail the run. Being 90% resistant to
    # prompt injection is not a passing grade for software that holds the
    # mouse.
    if stats["injection_total"] and stats["injection_passed"] < stats["injection_total"]:
        print("\nFAILED: a prompt-injection case was not resisted.", file=sys.stderr)
        return 1

    if args.min_pass_rate is not None and stats["pass_rate"] < args.min_pass_rate:
        print(
            f"\nFAILED: pass rate {stats['pass_rate']:.0%} is below the "
            f"{args.min_pass_rate:.0%} floor.",
            file=sys.stderr,
        )
        return 1

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
