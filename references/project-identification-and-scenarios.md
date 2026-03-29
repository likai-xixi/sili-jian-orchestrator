# Project Identification And Scenarios

## Identification Order

When attached to a target project, identify the project in this order:

1. explicit user path or project id
2. current working directory
3. `ai/state/project-meta.json`
4. `ai/state/START_HERE.md`

If identity remains ambiguous, stop before orchestration.

## Scenario Types

Classify the request into one of these flows:

### Vague Requirement

The user gives a broad outcome, concept, or partial requirement and does not want immediate implementation.

Required response:

- clarify scope
- separate raw, confirmed, and frozen requirements
- build or update the architecture and task tree
- avoid broad execution until planning approval

### New Project

The user starts from scratch or with an empty repository and wants strong governance from day one.

Required response:

- bootstrap governance structure
- initialize state machine and handoff files
- create workflow templates
- define milestones
- begin planning first

### Mid-Stream Takeover

The project already exists but governance or execution status is incomplete.

Required response:

- inventory the codebase and governance gaps
- patch missing state and reports
- establish the current status and next action
- create a takeover summary

### Session Recovery

A new chat or new round must recover a governed project.

Required response:

- read the recovery entry points in order
- summarize completed, in-progress, blocked, and next actions
- decide whether execution is allowed

### New Feature Into Existing Governance

The base project is already governed and the user wants to add a feature safely.

Required response:

- place the request into the requirements pool
- assess architectural impact
- update the task tree and milestone mapping
- re-run planning approval if the change affects boundaries, models, or the mainline
