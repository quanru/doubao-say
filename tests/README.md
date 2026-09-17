# Tests

- [`unit/`](unit/) contains fast Python behavior and component tests.
- [`contracts/`](contracts/) verifies packaging, releases, version alignment,
  Marketplace rules, and the Pages report builder.
- [`e2e/`](e2e/) exercises complete desktop flows on Ubuntu and Omarchy with
  Midscene and publishes HTML reports from GitHub Actions.
- [`manual/`](manual/) contains opt-in checks that require a real desktop,
  devices, credentials, or human observation.

`make test-unit` and `make test-contracts` run the two local automated layers.
`make test` runs both. See `CONTRIBUTING.md` before running anything under
`manual/`.
