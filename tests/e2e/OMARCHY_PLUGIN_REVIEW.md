# Omarchy plugin review on GitHub Actions

The `omarchy-plugin-smoke` project installs one public plugin at an exact Git
commit inside a disposable Omarchy 4.0.3 VM on a GitHub-hosted runner. Midscene
sees the guest desktop through VNC. The plugin never executes on the reviewer's
computer or on the runner host.

## Maintainer-triggered pilot

From a GitHub account with Actions write access to this repository:

```sh
gh workflow run midscene-omarchy-4.0.3.yml \
  --repo quanru/doubao-say \
  --ref research/omarchy-plugin-visual-review \
  -f project=omarchy-plugin-smoke \
  -f plugin_repository=tathagat11/omarchy-checklist-todo \
  -f plugin_sha=0b8dfdbdc5dc1deaff178ad727fa22f6e289423a \
  -f plugin_id=tathagat11.checklist-todo \
  -f plugin_open_method=open \
  -f visible_assertion='The Todos popup is open at the top center and shows its empty list.'
```

The equivalent form is under **Actions → Omarchy 4.0.3 → Run workflow**. Enter
the plugin's GitHub `owner/repository`, full 40-character commit SHA, manifest
ID, shell IPC method that opens the UI, and one visible result to check. The
input is bound to the exact commit; the runner does not follow the upstream
branch after validation. The workflow uploads the native Midscene HTML replay
and screenshots as `omarchy-midscene-omarchy-plugin-smoke`.

This pilot supports bar widgets with an IPC method that opens their UI. A visual
assertion is useful review evidence, but it is not a security verdict. The
Checklist Todo case additionally verifies state and disk persistence because a
visual model can miss a tiny control or misread a closed popup as an empty one.

## Public self-service boundary

This repository's prebuilt VM is a private GHCR artifact, and the model endpoint
is configured as Actions Secrets. GitHub `workflow_dispatch` also requires
write access. External authors cannot trigger this pilot workflow directly.
A public intake should accept a plugin URL and SHA, then have a maintainer or a
GitHub App dispatch this controlled workflow and link its report back to the
Marketplace Issue. Keep that intake separate from the official Marketplace
baseline: its policy never executes community code, while this workflow does so
only inside a disposable VM.
