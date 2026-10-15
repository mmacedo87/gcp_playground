#!/usr/bin/env python3
"""Posts the sticky PR comment and submits a formal PR review.

Mirrors the actions/github-script step of the original GitHub Actions
workflow: sticky comment with the full report, then a review matching the
verdict (APPROVE / REQUEST_CHANGES), falling back to a plain COMMENT review
if the review submission fails (e.g. GitHub rejects self-approval of your
own pull request).
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

GITHUB_API = "https://api.github.com"
MARKER = "<!-- dataform-pr-validation -->"
MAX_BODY_LENGTH = 60000

VERDICT_EVENTS = {
    "approve": "APPROVE",
    "skipped": "APPROVE",
    "request_changes": "REQUEST_CHANGES",
}
VERDICT_SUMMARIES = {
    "approve": "✅ Automated validation passed — approved.",
    "skipped": "⏭️ PR author is a CODEOWNER — validations bypassed.",
    "request_changes": "❌ Automated validation failed — manual review required. See the validation report comment.",
}


def api_request(method: str, url: str, token: str, body: Optional[dict] = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cloud-build-pr-validator",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def find_existing_comment(repo_full_name: str, pr_number: str, token: str) -> Optional[int]:
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments?per_page=100&page={page}"
        comments = api_request("GET", url, token)
        if not comments:
            return None
        for comment in comments:
            if MARKER in comment.get("body", ""):
                return comment["id"]
        if len(comments) < 100:
            return None
        page += 1


def post_comment(repo_full_name: str, pr_number: str, token: str, body: str) -> None:
    existing_id = find_existing_comment(repo_full_name, pr_number, token)
    if existing_id:
        url = f"{GITHUB_API}/repos/{repo_full_name}/issues/comments/{existing_id}"
        api_request("PATCH", url, token, {"body": body})
        print(f"PR comment updated on #{pr_number}")
    else:
        url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
        api_request("POST", url, token, {"body": body})
        print(f"PR comment created on #{pr_number}")


def submit_review(repo_full_name: str, pr_number: str, token: str, verdict: str) -> None:
    event = VERDICT_EVENTS[verdict]
    summary = VERDICT_SUMMARIES[verdict]
    url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
    try:
        api_request("POST", url, token, {"event": event, "body": summary})
        print(f"Submitted {event} review on #{pr_number}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"WARNING: could not submit {event} review ({exc.code}): {detail}")
        print("Falling back to a COMMENT review.")
        api_request("POST", url, token, {"event": "COMMENT", "body": summary})


def main() -> int:
    repo_full_name = os.environ["REPO_FULL_NAME"]
    token = os.environ["GITHUB_TOKEN"]

    pr_context = json.loads(Path("pr_context.json").read_text(encoding="utf-8"))
    pr_number = str(pr_context["pr_number"])
    verdict = Path("verdict.txt").read_text(encoding="utf-8").strip()

    body = Path("pr-validation-report.md").read_text(encoding="utf-8")
    if len(body) > MAX_BODY_LENGTH:
        body = body[:MAX_BODY_LENGTH] + "\n\n_(report truncated — see the build logs for full output)_"

    post_comment(repo_full_name, pr_number, token, body)
    submit_review(repo_full_name, pr_number, token, verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
