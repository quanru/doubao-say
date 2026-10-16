I’m experimenting with an entirely AI-driven workflow for PR validation. For this PR, I used AI agents and Midscene to run desktop acceptance checks and collect screenshots and step-by-step evidence for reviewers to inspect.

Tested **8997958** against **8b4eae6** in a disposable Omarchy desktop, using the real dropdown gallery with **Qt 6.11.2 / Quickshell 0.3.1**. The complete acceptance run passed, and all **37 recorded steps were reviewed** within this scope. The AI-assisted workflow produced deterministic checks; the acceptance run itself made no model calls.

[Full report](https://quanru.github.io/doubao-say/reports/38748420827/index.html) · [English Midscene evidence viewer](https://quanru.github.io/doubao-say/reports/38748420827/midscene-english.html)

| Check | Screenshot | Step evidence |
|---|---|---|
| Closed dropdown: wheel advances/reverses and clamps at the boundaries | <img src="https://quanru.github.io/doubao-say/reports/38748420827/raw-guest-candidate-05-clamp-last.png" width="320" alt="candidate-05-clamp-last"> | [View step](https://quanru.github.io/doubao-say/reports/38748420827/evidence-886f52ee-7a04-4d7a-ae64-ad34f7ca4459.html) |
| Open popup: wheel preserves selection and keeps the popup open | <img src="https://quanru.github.io/doubao-say/reports/38748420827/raw-guest-candidate-10-popup-trigger-wheel.png" width="320" alt="candidate-10-popup-trigger-wheel"> | [View step](https://quanru.github.io/doubao-say/reports/38748420827/evidence-280b17f8-8e52-4ebb-bae7-667ed0b4bd32.html) |
| Keyboard selection still works | <img src="https://quanru.github.io/doubao-say/reports/38748420827/raw-guest-candidate-12-keyboard-select-middle.png" width="320" alt="candidate-12-keyboard-select-middle"> | [View step](https://quanru.github.io/doubao-say/reports/38748420827/evidence-d5030f99-e4bd-4a76-8b7a-8c5e2a3ad018.html) |
| Horizontal wheel does not change selection | <img src="https://quanru.github.io/doubao-say/reports/38748420827/raw-guest-candidate-17-horizontal-right-rel-hwheel-verified.png" width="320" alt="candidate-17-horizontal-right-rel-hwheel-verified"> | [View step](https://quanru.github.io/doubao-say/reports/38748420827/evidence-949f6e94-0957-4e39-a633-6baa5c402755.html) |

The baseline did not respond to vertical wheel selection. Horizontal input was verified as `REL_HWHEEL ±1` on both revisions, with no vertical events. Original files and permissions were restored after testing.

**Not covered:** precision-touchpad/sub-notch accumulation, the first upward notch from an unmatched value, mouse selection of a different option, or business-panel E2E. Earlier failed attempts and the separate Qt 6.12 compatibility issue are documented in the report.

This is an AI-driven validation experiment, and I’d appreciate feedback on whether this evidence is useful for reviewing the change.
