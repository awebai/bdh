# Repository provenance

`github.com/awebai/bdh` is the canonical public repository for the `bdh` CLI.

It was recovered on 2026-08-23 from the complete public history of
`github.com/beadhub/bdh`. The imported `main` tip was
`124e56ac2fa9994c04f3a4c78294058b1417b5f6`, and all historical tags through
v0.11.7 were copied unchanged. The local `legacy-source` remote is fetch-only so
the historical repository cannot be changed accidentally.

The compatibility boundary is deliberate:

- Releases through v0.11.7 retain their original source, module path, and
  download URLs at `beadhub/bdh`.
- Releases from v0.12.0 use the module path and release location
  `github.com/awebai/bdh`.
- Existing installed clients remain usable. Run the canonical installer once to
  move an older installation to v0.12.0 or later; subsequent self-updates use
  `awebai/bdh`.

Related repositories:

- `awebai/beadhub-oss` contains the open-source BeadHub server wrapper.
- `awebai/beadhub-saas` contains the hosted BeadHub application.
- `awebai/aweb` contains the underlying coordination runtime and protocol.

This move does not change the hosted service, Render configuration, container
image namespace, or user credential format.
