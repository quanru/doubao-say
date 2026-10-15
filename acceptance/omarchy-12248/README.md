# PR 12248 independent desktop acceptance

Target: f88f533b6fd90178daf8165b0e8132a9b299d3e8. Baseline (merge base and observed base): 8b4eae66da2938ba9559f103b18dbf85cdf28a70.

Reuses the VM build, QMP input, pinned Midscene and log export approach from c7e0b9b7ca0218212c99e16c12de1b5964756fda. Runs only on a disposable public GitHub-hosted VM. No model keys, model calls, inherited budget, artifact-site publication or upstream comments. All conclusions require independent raw-image review. Virtual disk throttling is an observation aid, not a hardware benchmark. No product source is altered except installing exact baseline/head versions of the three changed product files.

Coverage: real staging/read/write/completion, Escape during actual staging, old process/fd and temporary-file cleanup, successful reopen, head restoration and configuration hash comparison. Image picker uses three fixed local PNGs, actual Right/Enter selection, cold/warm/forced-row-rebuild opens and exact result/index comparison. UI state conclusions remain pending visual review even if process assertions pass.

Local checks: Python compilation, Bash syntax, Node syntax, git diff --check. Repository make check blocked before lint because .venv/bin/python is unavailable; this is not a test pass.
