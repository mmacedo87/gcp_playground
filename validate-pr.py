#!/usr/bin/env python3
"""
PLACEHOLDER validation logic for the Cloud Build PoC.

Only `fetch_target_branch`, `check_branch_freshness`, `get_changed_files`,
`extract_changed_folders` and `get_commit_tags` do real work (git
operations). The remaining checks always return True until the real
Dataform validation rules are ported in here.
"""

import subprocess
from typing import List, Tuple


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def fetch_target_branch(target_branch: str) -> None:
    result = _run(["git", "fetch", "origin", target_branch])
    print(result.stdout)
    print(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch target branch '{target_branch}'")
    print(f"Fetched origin/{target_branch}")


def check_branch_freshness(target_branch: str) -> Tuple[str, int, bool]:
    """Dry-run merges origin/<target_branch> into HEAD to detect conflicts."""
    merge_base = _run(["git", "merge-base", "HEAD", f"origin/{target_branch}"])
    behind = _run(["git", "rev-list", "--count", f"HEAD..origin/{target_branch}"])
    behind_count = int(behind.stdout.strip() or "0")

    merge_result = _run(["git", "merge", "--no-commit", "--no-ff", f"origin/{target_branch}"])
    has_conflicts = merge_result.returncode != 0
    print(merge_result.stdout)
    print(merge_result.stderr)
    _run(["git", "merge", "--abort"])

    status = "conflicts detected" if has_conflicts else "no conflicts"
    print(f"Branch is {behind_count} commit(s) behind '{target_branch}' ({status}).")

    return merge_base.stdout.strip(), behind_count, has_conflicts


def get_changed_files(target_branch: str) -> List[str]:
    result = _run(["git", "diff", "--name-only", f"origin/{target_branch}...HEAD"])
    files = [f for f in result.stdout.splitlines() if f.strip()]
    print(f"Changed files ({len(files)}):")
    for f in files:
        print(f"  - {f}")
    return files


def extract_changed_folders(changed_files: List[str]) -> List[str]:
    return sorted({f.split("/")[0] for f in changed_files if "/" in f})


def get_commit_tags(ref: str = "HEAD") -> List[str]:
    result = _run(["git", "tag", "--points-at", ref])
    tags = [t for t in result.stdout.splitlines() if t.strip()]
    print(f"Tags pointing at {ref}: {tags or '(none)'}")
    return tags


def check_files_in_definitions(changed_files: List[str]) -> bool:
    print("PLACEHOLDER check: always passes until real rule is ported.")
    return True


def validate_folder_structure(changed_files: List[str]) -> bool:
    print("PLACEHOLDER check: always passes until real rule is ported.")
    return True


def check_required_tags(changed_folders: List[str]) -> bool:
    print("PLACEHOLDER check: always passes until real rule is ported.")
    return True


def check_version_conflicts_tags(commit_tags: List[str], target_branch: str) -> bool:
    print("PLACEHOLDER check: always passes until real rule is ported.")
    return True


def compile_dataform() -> bool:
    print("PLACEHOLDER: no Dataform project configured yet in this playground - skipping compilation.")
    return True
