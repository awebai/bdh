# Runnerless release lane

This is the primary `bdh` release path. It builds all platform archives once,
records their hashes and source commit, and publishes those exact bytes. GitHub
Actions is optional and is not needed for any step.

## 1. Prepare and review

Choose a stable semantic version at or above v0.12.0 and update release-facing
documentation. Commit the result, merge `origin/main`, and obtain an independent
ACK for the exact commit and cumulative diff. The release worktree must be clean
and `origin` must be `awebai/bdh`.

## 2. Build once

```bash
make release-build VERSION=0.12.0
```

The command first runs `go test ./...` and
`python3 -m unittest scripts/test_release.py`, then cross-compiles macOS, Linux,
and Windows archives for amd64 and arm64 under `.release-stage/v0.12.0/`. It
refuses an existing stage rather than overwriting it. `release-receipt.json`
records the full source commit, exact test gate, clean-tree assertion, Go
toolchain, platform list, sizes, and SHA-256 hashes.

Publication rejects a receipt without the required gate. In an urgent release
where the gate infrastructure itself is unavailable, a human may explicitly
record the accepted risk with
`RISK_ACCEPTANCE="<incident and reason>" make release-build VERSION=0.12.0`.
That reason is written into the public receipt and release notes. This is not
the normal path and must not be used to conceal a product test failure.

## 3. Verify the staged bytes

```bash
make release-verify VERSION=0.12.0
```

Verification checks the receipt, exact platform set, archive contents,
checksums, and embedded Go VCS metadata. It does not rebuild.

## 4. Publish the staged bytes

The explicit confirmation names both the only allowed repository and tag:

```bash
make release-publish VERSION=0.12.0 CONFIRM=awebai/bdh@v0.12.0
```

Publishing requires `git`, `go`, `gh`, GitHub authentication with release-write
access, and network access. It verifies that the receipt's source commit is on
`origin/main`, creates the tag at that exact commit if absent, creates or resumes
the GitHub release as a draft, uploads each staged asset, downloads every asset
again, compares its hash with the staged file, and only then makes the release
public. Upload is resumable: rerun the same command with the same stage and
confirmation.

Once a release is public, it is immutable. A retry only download-verifies the
public assets and succeeds if they exactly match the stage; it never replaces
assets on a public release.

No Render service or container image is changed by this release lane.

The optional GoReleaser workflow is manual-only and refuses tags that already
have a release, so pushing a runnerless release tag cannot start a second build
or replace its staged assets.
