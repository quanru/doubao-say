# Tests

The top-level `test_*.py` files cover automated Python behavior and package
contracts. The `manual_*.py` files are opt-in desktop checks documented in
`CONTRIBUTING.md`.

Desktop flows that exercise the whole application through a visible Linux or
Omarchy session live in [`e2e/`](e2e/). Those flows use Midscene as the test
runner and publish their HTML reports from GitHub Actions.
