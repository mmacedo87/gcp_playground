#!/usr/bin/env python3
"""Resolves the PR author via the GitHub API and writes pr_context.json.

PR number/base branch/head branch/commit already come from Cloud Build's
native pull-request substitutions ($_PR_NUMBER, $_BASE_BRANCH, $_HEAD_BRANCH,
$COMMIT_SHA) - only the author login still requires an API call.
"""

import json
import os
import sys
import urllib.request

GITHUB_API = "https://api.github.com"


def main() -> int:
    repo_full_name = os.environ["REPO_FULL_NAME"]
    pr_number = os.environ["PR_NUMBER"]
    base_ref = os.environ.get("BASE_REF", "")
    head_ref = os.environ.get("HEAD_REF", "")
    head_sha = os.environ.get("HEAD_SHA", "")
    token = os.environ["GITHUB_TOKEN"]

    url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cloud-build-pr-validator",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        pr = json.loads(response.read().decode("utf-8"))

    context = {
        "pr_number": pr_number,
        "author": pr["user"]["login"],
        "base_ref": base_ref or pr["base"]["ref"],
        "head_ref": head_ref or pr["head"]["ref"],
        "head_sha": head_sha or pr["head"]["sha"],
    }

    with open("pr_context.json", "w", encoding="utf-8") as handle:
        json.dump(context, handle)

    print(f"PR #{pr_number}: author={context['author']} base={context['base_ref']} head={context['head_ref']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
