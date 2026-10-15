#!/usr/bin/env python3
"""
CI wrapper for validate-pr.py

Runs the exact same validations as the local script, but:
  - takes the target branch / PR metadata from the GitHub Actions environment
  - captures the output of each check into a Markdown report
  - writes the verdict to $GITHUB_OUTPUT so the workflow can submit a PR review

Always exits 0 (except on unexpected errors) so the workflow can publish the
review before failing the job.
"""

import importlib.util
import io
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Callable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
REPORT_MARKER = "<!-- dataform-pr-validation -->"


def load_validator():
    """Loads validate-pr.py as a module (filename is not a valid identifier)."""
    script = REPO_ROOT / "validate-pr.py"
    if not script.exists():
        raise FileNotFoundError(f"validate-pr.py not found at {script}")

    spec = importlib.util.spec_from_file_location("validate_pr", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_check(name: str, func: Callable[[], bool]) -> Tuple[str, bool, str]:
    """Runs a single check, capturing its output. Returns (name, ok, log)."""
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            ok = bool(func())
    except SystemExit as exc:  # validate-pr.py calls sys.exit on hard errors
        buffer.write(f"\nCheck aborted (exit code {exc.code})\n")
        ok = False
    except Exception as exc:  # noqa: BLE001 - report instead of crashing the job
        buffer.write(f"\nUnexpected error: {exc}\n")
        ok = False

    log = strip_ansi(buffer.getvalue()).strip()
    print(f"::group::{name} -> {'PASS' if ok else 'FAIL'}")
    print(log)
    print("::endgroup::")
    return name, ok, log


def codeowners_contains(author: str) -> bool:
    """Checks if the PR author is listed in .github/CODEOWNERS."""
    codeowners = REPO_ROOT / ".github" / "CODEOWNERS"
    if not codeowners.exists() or not author:
        return False

    content = codeowners.read_text(encoding="utf-8")
    owners = set()
    for line in content.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        owners.update(token.lstrip("@").lower() for token in line.split()[1:])

    return author.lower() in owners


def build_report(verdict: str, results: List[Tuple[str, bool, str]], context: dict) -> str:
    """Builds the Markdown report posted as a PR comment."""
    header = {
        "approve": "### ✅ Validation passed — ready to merge",
        "request_changes": "### ❌ Validation failed — review required",
        "skipped": "### ⏭️ Validation skipped — PR author is a CODEOWNER",
    }[verdict]

    lines = [
        REPORT_MARKER,
        "## 🤖 Dataform PR Validation",
        "",
        header,
        "",
        f"- **Source branch:** `{context['head_ref']}`",
        f"- **Target branch:** `{context['base_ref']}`",
        f"- **Commit:** `{context['head_sha'][:8]}`",
        "",
    ]

    if results:
        lines += ["| Check | Result |", "| --- | --- |"]
        for name, ok, _ in results:
            lines.append(f"| {name} | {'✅ PASS' if ok else '❌ FAIL'} |")
        lines.append("")

        failed = [name for name, ok, _ in results if not ok]
        if failed:
            lines += ["**Failed checks:**"] + [f"- {name}" for name in failed] + [""]

        lines.append("#### Details")
        for name, ok, log in results:
            icon = "✅" if ok else "❌"
            lines += [
                f"<details><summary>{icon} {name}</summary>",
                "",
                "```text",
                log if log else "(no output)",
                "```",
                "",
                "</details>",
                "",
            ]
    else:
        lines += [
            "The PR author is listed in `.github/CODEOWNERS`, so all validation "
            "checks were bypassed.",
            "",
        ]

    return "\n".join(lines)


def write_outputs(verdict: str, report: str, failed_count: int):
    """Writes workflow outputs and the report file."""
    report_path = REPO_ROOT / "pr-validation-report.md"
    report_path.write_text(report, encoding="utf-8")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as handle:
            handle.write(f"verdict={verdict}\n")
            handle.write(f"failed_count={failed_count}\n")
            handle.write(f"report_path={report_path}\n")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(report)


def main() -> int:
    validator = load_validator()

    context = {
        "base_ref": os.environ.get("BASE_REF", "dev"),
        "head_ref": os.environ.get("HEAD_REF", ""),
        "head_sha": os.environ.get("HEAD_SHA", ""),
        "author": os.environ.get("PR_AUTHOR", ""),
    }
    target_branch = context["base_ref"]

    print(f"Target branch: {target_branch}")
    print(f"Source branch: {context['head_ref']} ({context['head_sha']})")
    print(f"PR author: {context['author']}")

    if codeowners_contains(context["author"]):
        report = build_report("skipped", [], context)
        write_outputs("skipped", report, 0)
        return 0

    validator.fetch_target_branch(target_branch)

    results: List[Tuple[str, bool, str]] = []

    def check_branch_freshness() -> bool:
        _, _, has_conflicts = validator.check_branch_freshness(target_branch)
        return not has_conflicts

    results.append(run_check("CHECK 1: Branch freshness / merge conflicts", check_branch_freshness))

    changed_files = validator.get_changed_files(target_branch)
    results.append(
        run_check(
            "CHECK 2: Files in definitions/",
            lambda: validator.check_files_in_definitions(changed_files),
        )
    )
    results.append(
        run_check(
            "CHECK 2b: Folder structure",
            lambda: validator.validate_folder_structure(changed_files),
        )
    )

    changed_folders = validator.extract_changed_folders(changed_files)
    results.append(
        run_check(
            "CHECK 3: Git tag validation",
            lambda: validator.check_required_tags(changed_folders),
        )
    )

    commit_tags = validator.get_commit_tags("HEAD")
    results.append(
        run_check(
            "CHECK 4: Semantic versioning",
            lambda: validator.check_version_conflicts_tags(commit_tags, target_branch),
        )
    )

    results.append(run_check("CHECK 5: Dataform compilation", validator.compile_dataform))

    failed_count = sum(1 for _, ok, _ in results if not ok)
    verdict = "approve" if failed_count == 0 else "request_changes"

    report = build_report(verdict, results, context)
    write_outputs(verdict, report, failed_count)

    print(f"Verdict: {verdict} ({failed_count} failed check(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

