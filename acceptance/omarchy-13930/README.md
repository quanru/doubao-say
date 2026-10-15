# PR 13930 isolated acceptance checkpoint

Status: real VM workflow implemented and launched independently. Results and
independent image review are pending. The prerequisite workflow remains separate
and its success must never be reported as desktop CI passing.

Pinned baseline and candidate are in `pins.json`. The production diff is exactly
32 added lines in `shell/Ui/Dropdown.qml`. Do not modify production to pass tests.
Use `omarchy dev ui-preview dropdown`, the real shared-component gallery, not a
business panel. Its options are omarchy.clock, omarchy.weather, omarchy.power.

Required comparison in a disposable VM, with the same theme, size and scale:

1. Closed control: down, down, down, up, up, up. Candidate steps and clamps;
   baseline does not acquire the newly introduced closed-control behavior.
2. Open the popup, wheel over the trigger, confirm no closed-control mutation.
3. Select by click; reopen and select by Down/Up/Enter; test Escape dismissal.
4. Exercise an unmatched value using a clearly recorded, reversible gallery-only
   setup change. Never change Dropdown.qml; restore and hash-check gallery bytes.
5. Query the actual QMP schema and guest input capabilities before horizontal
   wheel injection. QMP documents wheel-left/right, but a host enum is not proof
   of delivery through the chosen virtual device and compositor. Observe guest
   REL_HWHEEL and the visible control. Vertical wheel does not cover this case.
6. Fine deltas need an actual supported high-resolution input route. Ordinary
   QMP wheel buttons do not establish touchpad/sub-notch coverage. If unsupported,
   mark this case untested; do not substitute a direct JS/QML function call.

Use deterministic Midscene operations/observations without model configuration.
Retain original Midscene HTML, step identifiers, raw screenshots and all failures.
Independently inspect images and configuration restoration after the same complete
acceptance CI run succeeds. No such run exists for this checkpoint.

Reference only: previous harness c7e0b9b7ca0218212c99e16c12de1b5964756fda.
Do not inherit its model budget, product patch bundle, credentials, publishing
steps or PR15184-specific guest setup. The current environment lacks QEMU/KVM and
its GitHub API calls return 403, including the attempt outside the default sandbox.

QMP reference: https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html

The real workflow is `.github/workflows/omarchy-13930-vm.yml`, triggered only by
`ci/.run-vm`. It reuses the existing pinned ISO builder and locked dependencies,
uses no model configuration, and exports `PR13930_EVIDENCE_*` log records. A
read-only gallery Timer observes actual values and geometry; production Dropdown
bytes are checked against the pinned head and swapped only for the exact baseline.
The built-in unmatched initial value is `Clock`, so no setup value patch is needed.
Horizontal injection is diagnostic until guest delivery is independently verified.
