# Target Mode Vs Skill Mode

Use this reference to avoid creating project governance files in the wrong place.

## Skill Bundle Mode

Treat the current directory as a skill bundle when it contains any of the following:

- `SKILL.md`
- `agents/openai.yaml`
- `assets/project-skeleton/`
- `scripts/bootstrap_governance.py`

In this mode:

- edit the skill package itself
- refine prompts, templates, workflows, references, and scripts
- do not create `ai/`, `tests/`, or `workflows/` for a product repository unless the user explicitly asks for an example project inside the skill package

## Project Mode

Treat the current directory as a target project when it contains any of the following:

- `.git/`
- `src/`
- `tests/`
- `docs/`
- `ai/`
- a clear user statement that the directory is the project root

In this mode:

- inspect governance readiness
- backfill missing project-local state
- bootstrap governance from `assets/project-skeleton/` if needed
- produce takeover or recovery summaries before coding

## Unknown Mode

If the location is ambiguous:

- stop before execution
- explain what is missing
- ask for the intended target project directory or whether the user wants to edit the skill package itself
