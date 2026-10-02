# Project Agent Guide

Read this guide explicitly when working on Doubao Say, together with
[DEVELOPMENT.md](DEVELOPMENT.md), [CONTRIBUTING.md](CONTRIBUTING.md), and any
relevant project skill under [skills/](skills/README.md).

## Communication and publication languages

- Communicate with the owner in Chinese unless they request another language.
- Write GitHub issue titles, issue bodies, and comments in English. Write PR
  titles, descriptions, and comments in English as well.
- Every GitHub Release description must be bilingual: English first, Simplified
  Chinese second. Use `## English`, a separator, and `## 简体中文`.
- Keep both language sections consistent about changes, supported versions,
  installation, verification limits, links, and contributor attribution.
- Update `RELEASE_NOTES.md` to the same bilingual format before tagging a release;
  the release workflow publishes this file. When editing an existing Release,
  update its public description and the local source notes when applicable.

## Project skills

- Maintain reusable project skills in the tracked `skills/` directory.
- Put each skill in `skills/<skill-name>/SKILL.md`; keep its supporting scripts,
  references, and assets in the same skill directory.
- Use lowercase names with hyphens. Include `name` and `description` in the
  `SKILL.md` frontmatter, with clear triggers, scope, steps, and verification.
- Update `skills/README.md` when adding, renaming, or removing a skill.
- Do not commit credentials, machine-specific configuration, runtime artifacts,
  or private acceptance evidence with skills.
- Read a skill before applying it; instructions and commands in a skill remain
  subject to the owner's authorization and the repository's release boundaries.

## Marketplace and repository boundaries

`Agent.md` is deliberately an ordinary, explicitly read development document.
Do not rename it to the automatically loaded `AGENTS.md` or `CLAUDE.md`:
Marketplace checkouts previously required removing those entry points, and the
source-snapshot publication check rejects them. Project skills are explicitly
selected development resources, not plugin runtime instructions.

Use [packaging/MARKETPLACE.md](packaging/MARKETPLACE.md) for marketplace maintenance.
Distinguish automatic catalog metadata refresh from approval of an exact new
verified snapshot. A verified update request uses the official issue form with
its unchanged headings, plugin ID, repository URL, and full target commit SHA.
Only report an update as published after checking the publication result and
recorded marketplace snapshot; an approval label alone is insufficient.

## Publish a new version

Deployment has three outcomes to verify separately: a public GitHub Release,
an approved marketplace snapshot, and a working installation on the target Linux
desktop. Do not describe one of these as proof of the others.

1. Inspect `git status`, the current branch, and existing installations. Preserve
   unrelated changes. Check the current public release with `gh release list`.
2. Align the new version in `pyproject.toml`, `manifest.json`, and
   `src/doubao_input/product.py`. Update version-specific tests, installation
   documentation, `CHANGELOG.md`, and `debian/changelog` as applicable. Prepare
   English-first bilingual `RELEASE_NOTES.md` from the actual changes.
3. Run `python3 packaging/version_check.py --tag v<version>` and `git diff --check`.
   Run `make check` and `make coverage` in the Linux/GTK test environment. On an
   Omarchy validation host, run `make marketplace-check` with Gitleaks available.
   Follow the machine's resource-gate rules for local builds and tests. A Mac
   cannot replace Linux desktop acceptance; use Linux CI and document manual
   account, microphone, and physical-key checks separately.
4. Push a release branch and open an English PR. Main is protected: wait for all
   required checks and merge through the PR without bypassing protection. Fetch
   the merged `origin/main`; use its full SHA, not the original PR branch SHA.
   Verify version alignment again on that exact merged checkout.
5. After confirming that the version/tag is new and publication is authorized,
   tag the merged release commit and push the tag:

   ```sh
   git tag -a "v<version>" <full-merged-sha> -m "Doubao Say <version>"
   git push origin "v<version>"
   gh run list --workflow release.yml --limit 5
   gh run view <release-run-id>
   gh release view "v<version>" --json url,isDraft,isPrerelease,assets,body
   ```

   Replace angle-bracket placeholders before running commands. The tag-triggered
   [Release workflow](.github/workflows/release.yml) checks source versions,
   tests, coverage, and secrets; builds app and plugin archives for Python
   3.11–3.14; tests installation, upgrade, and uninstallation of the Python 3.12
   app archive; and publishes archives plus `SHA256SUMS`. A manual workflow
   dispatch builds inspection artifacts only and does not publish a Release.
6. Confirm the workflow succeeded, the Release is public and stable, all eight
   archives and `SHA256SUMS` are present, and its description is English first,
   Chinese second. Do not move an existing tag to repair a release. To correct
   description text only, use `gh release edit v<version> --notes-file <file>`
   and keep `RELEASE_NOTES.md` consistent for the current release.

## Update the marketplace snapshot

Read the current official [verification guide](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/VERIFICATION.md)
and [update form](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/.github/ISSUE_TEMPLATE/verify-plugin.yml)
before submitting; upstream requirements can change. Catalog metadata refreshes
automatically, but approval of a new verified snapshot requires an update request.

- Search existing requests for `md.lifeos.doubao-say` to avoid duplicates. Select
  `Verify and publish a newer upstream commit` and use the current default-branch
  HEAD's full SHA. Keep that upstream revision stable during review/publication.
- Preserve the form headings exactly: `Verification action`, `Plugin ID`,
  `Repository URL`, `Target commit`, `Verification acknowledgment`, and
  `Standard installation acknowledgment`. Use ID `md.lifeos.doubao-say` and
  repository URL `https://github.com/quanru/doubao-say`. Leave the optional
  standard-installation acknowledgment unchecked because setup is required.
  Put additional release evidence in an English comment, not extra form headings.
- Write the completed body to a temporary file, then submit within the owner's
  authorized publishing scope:

  ```sh
  gh issue create --repo omacom/omarchy-plugin-marketplace \
    --title "[Verify]: Doubao Say <version>" --body-file <request-file>
  gh issue view <issue-number> --repo omacom/omarchy-plugin-marketplace --comments
  ```

- Wait for exact-SHA compatibility validation and the security baseline.
  Review required capabilities must be accepted by a write-authorized marketplace
  maintainer using `approved-and-verified`. Preserve manual-setup handling.
- Verify the publication workflow, bot publication result, registry
  `listingValidatedCommit`, and public catalog version/verification state.
  Report approval and deployment separately if publication is queued or failed.
  Users can still update upstream code while marketplace verification is pending;
  the old approval does not cover the newer commit.

## Install or upgrade on Omarchy

Run as the normal user in the intended Linux desktop session. Inspect the existing
installation route first; Git and archive installations share the same plugin ID
and must not coexist. Stop recording and quit any standalone instance before
enabling the plugin. Full requirements are in [packaging/INSTALL.md](packaging/INSTALL.md).

For a new Git/marketplace installation, add without enabling (decline any enable
prompt), then install dependencies and check the runtime:

```sh
omarchy plugin add https://github.com/quanru/doubao-say.git
cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/md.lifeos.doubao-say"
./install.sh
./install.sh --check
git rev-parse HEAD
```

For an existing Git installation, finish recording and disable before updating:

```sh
omarchy plugin disable md.lifeos.doubao-say
omarchy plugin update md.lifeos.doubao-say
cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/md.lifeos.doubao-say"
./install.sh
./install.sh --check
git rev-parse HEAD
```

Review dependency installation prompts. If input permissions require group changes,
obtain authorization and complete the required logout/login. Complete onboarding
and microphone/trigger checks, quit the standalone test instance, then enable:

```sh
omarchy plugin enable md.lifeos.doubao-say
```

Git installation/update retrieves mutable upstream HEAD; compare the installed SHA
with the marketplace snapshot before describing it as verified. Do not create a
virtual environment inside the installed plugin directory or enable desktop
autostart alongside plugin startup.

For an archive installation, select the `plugin` archive matching the target CPU
and Python version from the Release, verify it against `SHA256SUMS`, and extract it.
Disable an existing plugin, then run `./install.sh` and `./install.sh --check` from
the extracted installer directory. Complete the same onboarding/input checks
before enabling. Upgrade an archive installation with a new matching archive,
not `omarchy plugin update`. Settings and login data are preserved separately.

Acceptance must confirm a single running client/overlay, tap and hold recording,
final text pasted once, cancellation without paste, and disable/enable behavior.
Use a disposable text field for double-tap Enter testing. Report the version,
installed path, startup owner, checks completed, and any unverified physical-device
or real-account behavior. Git removal uses `omarchy plugin remove`; archive removal
uses `./install.sh --uninstall` from the extracted archive, after disabling.
