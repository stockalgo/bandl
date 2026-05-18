# PyPI Trusted Publishing (GitHub Actions)

This repository publishes **bandl** to [PyPI](https://pypi.org/project/bandl/) using **Trusted Publishing** (OpenID Connect). No long-lived PyPI API token is stored in GitHub.

## What runs in CI

| File | When |
|------|------|
| [.github/workflows/publish.yml](../.github/workflows/publish.yml) | Push of a tag matching `v*.*.*` (e.g. `v0.2.0`), or manual **Run workflow** |

The job builds with `python -m build` and uploads with [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish), **pinned to a full git SHA** in the workflow file (supply-chain hygiene). For **tag** pushes, a step asserts that `vX.Y.Z` matches `project.version` in `pyproject.toml` before building.

## Your checklist (one-time setup)

### 1. GitHub: create the `pypi` environment

1. Open **GitHub** → repository **stockalgo/bandl** → **Settings** → **Environments**.
2. **New environment** → name: **`pypi`** (must match the workflow).
3. Optional but recommended: enable **Required reviewers** so uploads need approval before running on `workflow_dispatch` or tag pushes.

### 2. PyPI: add a pending trusted publisher

1. Log in to [pypi.org](https://pypi.org) with the account that **owns or will own** the `bandl` project.
2. Go to **Your projects** → **bandl** → **Manage** → **Publishing** (or create the project first if it does not exist—see below).
3. Add a **pending** trusted publisher:
   - **Publisher type:** GitHub
   - **Owner / Organization:** `stockalgo` (use the exact GitHub owner of this repo)
   - **Repository name:** `bandl`
   - **Workflow name:** `publish.yml` (only the filename)
   - **Environment name:** `pypi`

4. Save. PyPI will show the publisher as **pending** until the first successful run of that workflow.

### 3. First release (version and tag)

1. On the branch you will release from (usually `master`), set **`version`** in [`pyproject.toml`](../pyproject.toml) to the release version (e.g. `0.2.0`).
2. Commit and push, merge if needed.
3. Create and push an annotated tag (example):

   ```bash
   git tag -a v0.2.0 -m "Release 0.2.0"
   git push origin v0.2.0
   ```

   The tag **must** match `vMAJOR.MINOR.PATCH` (same pattern as in `publish.yml`).

4. Watch **Actions** → **Publish to PyPI**. After success, the pending publisher on PyPI becomes **active**.

### 4. If the `bandl` project does not exist on PyPI yet

- Create the project in the PyPI UI, **or**
- Perform **one** initial upload with a [PyPI API token](https://pypi.org/manage/account/token/) via `twine` from your machine, **then** add the trusted publisher as above.

Your PyPI account email does **not** need to match your GitHub email; only **ownership** of the PyPI project and **write** access to the GitHub repo matter.

## Manual publish (without a tag)

In **Actions** → **Publish to PyPI** → **Run workflow**: use this for testing or emergency releases **after** Trusted Publishing is active. Ensure `pyproject.toml` on the selected branch/ref already has the correct **version** (PyPI rejects re-uploading the same version).

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| "Permission denied" / OIDC errors | Workflow filename is exactly `publish.yml`; PyPI publisher uses the same **owner**, **repo**, **workflow name**, and **environment** `pypi`. |
| "File already exists" | Bump `version` in `pyproject.toml`; each PyPI upload needs a new version. |
| Fork PRs | Publishing only makes sense from **stockalgo/bandl**; protect `master` and tags as usual. |

## TestPyPI (optional)

To try the flow without touching the real index, add a second job or separate workflow targeting TestPyPI and register a **separate** trusted publisher on [test.pypi.org](https://test.pypi.org) for the same repo/workflow pattern. The action supports `repository-url: https://test.pypi.org/legacy/`.
