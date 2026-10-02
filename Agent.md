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
