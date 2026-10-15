# Cloud Build PR validation (playground)

`dev` is the target branch for test PRs. A Cloud Build trigger
(`gcp-playground-pr-validation`, project `sandbox-vf-alemanha-5340`) runs
`cloudbuild/validate-pr.cloudbuild.yaml` on every pull request against this
branch: it runs the checks in `validate-pr.py` and submits a GitHub PR
review (Approve / Request changes), plus a sticky comment with the full
report.

`validate-pr.py` is currently a **placeholder** — most checks return `True`
unconditionally. Replace it with the real Dataform validation logic when
ready.

`validate_pr_ci.py` and `validation_ci.yml` are the original GitHub Actions
files, kept here for reference. They are not used by the Cloud Build
pipeline.
