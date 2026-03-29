# Review And Approval

## Department Model

Use these peer agents as review lenses:

- `libu2` for backend and business logic
- `hubu` for database and consistency
- `gongbu` for frontend and interaction
- `bingbu` for testing and regression
- `libu` for documentation and handoff
- `xingbu` for build, deployment, and release safety

## Review Matrix

Formal governed rounds should produce `ai/reports/department-approval-matrix.md` containing:

- round id
- review scope
- each department's opinion on the other five departments
- blockers
- warnings
- suggestions
- responses from reviewed parties
- closure status for findings
- recommendation on final audit

## Final Audit

Final audit should be executed by `duchayuan`.

Final audit should check:

- handoff completeness
- matrix completeness
- test report viability
- blocker count
- change summary
- gate report
- state freshness
- mainline regression status
- rollback readiness when release is in scope

Allowed conclusions:

- `PASS`
- `PASS_WITH_WARNING`
- `REWORK`
- `BLOCKER`
- `FAIL`
- `REDESIGN`
