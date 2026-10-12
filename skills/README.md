# Project Skills

This tracked directory stores reusable development skills for Doubao Say.
Read [Agent.md](../Agent.md) for project language and publication conventions.

No project skills have been added yet. Add a skill when a repeatable workflow
needs its own instructions; do not create placeholders for hypothetical tasks.

## Layout

```text
skills/
  README.md
  <skill-name>/
    SKILL.md
    scripts/       # Optional reusable scripts
    references/    # Optional supporting documentation
    assets/        # Optional templates or static resources
```

Each `SKILL.md` starts with YAML frontmatter containing `name` and `description`.
The description should explain when to use the skill. The body should define its
scope, prerequisites, steps, expected outputs, and verification. Keep supporting
paths relative to the skill directory and add each real skill to an index here.

Skills are explicitly selected development resources. Keep secrets, local session
state, installed dependencies, and generated reports out of this directory.
