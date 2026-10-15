# Cloud Build PR validation (playground)

`dev` is the target branch for test PRs. A Cloud Build trigger
(`gcp-playground-pr-validation`, project `sandbox-vf-alemanha-5340`) runs
`cloudbuild/validate-pr.cloudbuild.yaml` on every pull request against this
branch: it runs the checks in `validate-pr.py` and submits a GitHub PR
review (Approve / Request changes), plus a sticky comment with the full
report.

`validate-pr.py` now contains the real Dataform validation logic (branch
freshness, `definitions/` folder structure, git tag / semver validation,
Dataform compilation). **CHECK 5 (Dataform compilation) will fail until a
real Dataform project (with `workflow_settings.yaml`) exists in this repo** —
that's expected, not a bug.

`validate_pr_ci.py` and `validation_ci.yml` are the original GitHub Actions
files, kept here for reference. They are not used by the Cloud Build
pipeline.
2.2
