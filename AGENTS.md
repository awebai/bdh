# Agent Instructions

## Project context

Read [docs/sot.md](docs/sot.md) before making architectural or release changes.
This repository is the canonical public source for the `bdh` CLI. Starting with
v0.12.0, its Go module, installer, self-update endpoint, and releases live at
`github.com/awebai/bdh`. The legacy `github.com/beadhub/bdh` repository and its
tags through v0.11.7 are preserved for compatibility and provenance; do not
publish new releases there.

## Coordination

The active workspace instructions are authoritative. This repository may be
worked on from a larger coordinated workspace; use that workspace's configured
coordination tool and identity. Do not infer identity from this repository or
run coordination commands here when the active workspace says to run them
elsewhere.

## Development

```bash
make build
make test
make fmt
```

- Keep `bdh` compatible with existing `.beadhub` files and BeadHub servers.
- Preserve passthrough behavior: ordinary commands still reach `bd` when the
  coordination service is unavailable, except for intentional claim-conflict
  protection.
- Do not redesign activation credentials without an observed compatibility or
  security defect and an explicit migration plan.
- Use focused tests while iterating and the full suite once before review.

## Review and release

- Obtain an independent review of the exact commit and diff before pushing or
  tagging a release.
- A release must be buildable and publishable without GitHub Actions. Use the
  checked-in build-once/stage/verify/publish lane documented in
  [release/README.md](release/README.md).
- Build artifacts once from a clean reviewed commit. Publish the staged bytes;
  never rebuild during publish.
- The publish step must verify the tag target, uploaded asset hashes, and the
  canonical `awebai/bdh` destination.
- GitHub Actions are an optional automation path, not a release dependency.
