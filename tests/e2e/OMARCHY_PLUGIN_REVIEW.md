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
ID, shell action that opens the UI (`summon` for panels, overlays, and menus;
an IPC method such as `open` for bar widgets), and one visible result to check. The
input is bound to the exact commit; the runner does not follow the upstream
branch after validation. The workflow uploads the native Midscene HTML replay
and screenshots as `omarchy-midscene-omarchy-plugin-smoke`.

This pilot supports shell-summoned panels, overlays, menus, and bar widgets with
an IPC method that opens their UI. A visual
assertion is useful review evidence, but it is not a security verdict. The
Checklist Todo case additionally verifies state and disk persistence because a
visual model can miss a tiny control or misread a closed popup as an empty one.

## Public review request (pilot)

After this workflow and the Issue form are merged into the default branch, an
external author can open **Issues → New issue → Omarchy plugin visual review**.
They provide the public repository URL, exact SHA, manifest ID, IPC method,
and one visible result. A maintainer checks the request and adds the
`midscene-review` label. That label starts this repository's Actions workflow;
the workflow validates the form, runs the exact commit in its disposable VM,
and comments a run link on the Issue. The author does not need Actions write
access, a GHCR token, or a model API key. The label is the spend and code
execution gate. The Issue trigger is a pilot and has not yet been exercised
end to end on the default branch.

## Hosting boundary

This repository's prebuilt VM is a private GHCR artifact, and the model endpoint
is configured as Actions Secrets. GitHub `workflow_dispatch` also requires
write access, so external authors cannot use the manual Actions form directly.
The public Issue form provides intake without sharing those credentials. A
dedicated review repository would make this entry point easier to discover and
avoid mixing review requests with Doubao Say product issues. A thin GitHub App
could later listen for an approved label on official Marketplace Issues and
dispatch this same controlled workflow; the App would only handle routing and
report links, while the VM and model remain in Actions. Keep the visual result
separate from the official Marketplace baseline: its policy never executes
community code, while this workflow does so only inside a disposable VM.
