# GitHub pilot setup and first real PRs

Setup completed on 21 November 2026:

- Public tool repository: https://github.com/SharmaKunal14/smart-ci
- Tool commit used by the workflow: `c9f467476e81c46902885d0802e8f3acfbc8bdef`.
- Public fork: https://github.com/SharmaKunal14/packaging
- Onboarding PR: https://github.com/SharmaKunal14/packaging/pull/1
- Fork default branch: `smartci-pilot`, initially at reviewed packaging commit
  `929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5`. Upstream `main` is preserved separately.
- The onboarding workflow targets pushes to `smartci-pilot` and PRs. It replaces
  one Ubuntu/Python 3.14 cell and preserves the remaining native test jobs.
- The pilot branch requires a PR and `All pass`, including for administrators;
  force pushes and deletion are disabled. Approval count is zero so this personal
  pilot does not require you to approve your own PR. This is **not** independent
  peer-review enforcement; enterprise workflow governance remains a later gate.
- Actions is disabled on both repositories. No hosted CI run has been launched.
  Smart CI itself has no workflow to enable; only the packaging fork needs Actions.

Your existing GitHub CLI login works. Do not create or paste a personal access
token into code, workflow YAML, chat or the terminal. The public tool checkout
needs no extra cross-repository secret. The workflow uses GitHub's short-lived
token for its isolated read-only artifact lookup.

## 1. Review the onboarding PR

Open PR #1 and inspect **Files changed**. Confirm that it targets
`SharmaKunal14/packaging:smartci-pilot`, not `pypa/packaging`. It changes only
`.github/workflows/test.yml`. The tool SHA is pinned, the authoritative native full
command remains, and proposal publication happens before full execution.

Do not merge yet: with Actions disabled, the required check will be pending.

## 2. Enable the pilot workflow when ready

In the fork, open **Settings → Actions → General**, allow GitHub Actions, and save.
Then open **Actions**. If GitHub shows the fork-specific workflow enablement
acknowledgement, complete it. Enable the **Test** workflow and disable unrelated
inherited workflows before triggering a run. In particular, do not enable release
or scheduled workflows merely to test Smart CI.

Inspect the registered workflows with:

```sh
gh workflow list --all --repo SharmaKunal14/packaging
```

For each unrelated workflow listed, disable it by its numeric ID. For example,
replace `WORKFLOW_ID` with an actual ID from that list:

```sh
gh workflow disable WORKFLOW_ID --repo SharmaKunal14/packaging
gh workflow enable test.yml --repo SharmaKunal14/packaging
```

If the list is empty, finish the Actions-tab enablement and refresh before
continuing. GitHub documents [enabling and disabling workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).
Keep **Workflow permissions** read-only and do not enable permission for Actions
to create or approve PRs; this workflow does not need it.

The existing Test workflow includes many platform/version and downstream jobs.
Shadow mode adds overhead and does not reduce their execution. Standard hosted
runner compute for public repositories is free under GitHub's published billing
rules, but that is not a guarantee about all account storage or other usage.
Review [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
and your account's spending controls before activation. No AWS or model billing
is involved.

## 3. Trigger the onboarding run

The PR was opened while Actions was disabled. Close and reopen it to produce a
fresh supported PR event; merely marking a PR ready or refreshing the page is not
the same event:

```sh
gh pr close 1 --repo SharmaKunal14/packaging
gh pr reopen 1 --repo SharmaKunal14/packaging
gh run list --repo SharmaKunal14/packaging --workflow test.yml --limit 5
```

Open the run in the Actions tab. Look for **Ubuntu / 3.14 (Smart CI shadow)**,
the proposal/result artifacts, and the comparison summary. Expect
`BASELINE_UNAVAILABLE_OR_INCOMPATIBLE` and full execution: there is no successful
protected baseline yet. Optional lookup warnings on this first run are expected.
The native test and coverage gates must still pass. A missing result/comparison is
incomplete analysis, not a successful shadow validation.

If any job fails, inspect it before merging. Upstream jobs can fail independently
of Smart CI; do not remove required checks or label the whole integration verified
just because the optional analysis step passed.

## 4. Merge and establish the protected Linux baseline

After reviewing the diff and seeing a successful full workflow, merge PR #1 in
GitHub (or use the command below). Do not use `--admin` to bypass checks:

```sh
gh pr merge 1 --repo SharmaKunal14/packaging --squash
```

This push to protected `smartci-pilot` triggers the baseline run. Wait for the
entire workflow to finish successfully. Verify a
`smartci-baseline-linux-py314-<attempt>` artifact exists and the comparison says
`baseline_eligible: true`. Missing/failed/skipped Linux cases, discovery gaps or
an unsuccessful workflow mean there is no usable baseline. Do not substitute the
Mac's reviewed-skip result.

## 5. Open a small source-change PR

Use the separate fork checkout created for this task. The managed Phase 4 demo
checkout remains untouched:

```sh
cd /Users/kunalsharma/Fun/project/smart-ci/demo-output/github/packaging
git fetch origin
git switch -c codex/phase5-license origin/smartci-pilot
printf '\n# Smart CI pilot: verify deterministic source-file impact.\n' >> src/packaging/licenses/_spdx.py
git add src/packaging/licenses/_spdx.py
git commit -m "Exercise license dependency planning without changing behavior"
git push -u origin codex/phase5-license
gh pr create --repo SharmaKunal14/packaging --base smartci-pilot \
  --head codex/phase5-license \
  --title "Verify automatic license test impact planning" \
  --body "Comment-only source change to exercise deterministic PR planning. Native full execution remains authoritative."
```

With compatible evidence, the prior local graph suggests the license and metadata
test files should be selected. That is an expectation to verify, not a hosted
result already observed. Check `mode: subset`, `execution: full`, dependency-path
reasons, and context containing the actual tested merge SHA. If the environment
or evidence changed, full fallback is the correct behavior; inspect its reason.

Next, rerun the same revision and compare proposal digests, push a dependency
change to the PR, and verify evidence refresh. A seeded failing-test experiment
should also confirm that a failing native job cannot become green through analysis.
These are remaining Phase 5 live acceptance checks, not completed work.

## Controls and rollback

- `SMARTCI_FORCE_FULL=true` repository variable forces a full proposal.
- `SMARTCI_DISABLE_ANALYSIS=true` runs the original native path without the
  observer. Both preserve full execution.
- Disable the Test workflow to stop new runs. Disabling does not cancel an
  already-running job; cancel active runs separately in the Actions tab.
- Revert the onboarding PR to restore the original matrix cell. Keep experiments
  inside your fork; do not send them upstream.

Local verification before publishing: 164 tests, formatter, linter and strict
typing passed; the actual SHA-pinned generated workflow passed actionlint 1.7.12
and `git diff --check`. Public source publication, fork ancestry, pilot revision,
branch protection and disabled Actions settings were checked through GitHub.
Hosted execution remains unverified until the activation steps above are run.
