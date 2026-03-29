# Requirement Communication Template

Use this template whenever you are discussing requirements with the customer, especially when the project is new, vague, or missing documentation.

## 1. Confirmed Facts

- What is already confirmed in this round?
- Which goals, users, scope items, and acceptance rules are fixed?

## 2. Current Implementation Baseline

- Use this section for takeover projects with existing code.
- Summarize what is already implemented, what is partially implemented, and what is still missing.
- Link to `ai/reports/current-implementation-summary.md` when applicable.

## 3. Missing Functional Gaps

- Which necessary functions, rules, edge cases, or supporting capabilities are still missing from the current requirement?
- Typical examples: permissions, notifications, audit logs, rollback paths, exports, search, drafts, error handling, and approval rules.

## 4. Better Options And Improvements

- Proactively propose better approaches when they reduce risk, simplify delivery, improve maintainability, or improve user experience.
- For each suggestion, record:
  - suggestion
  - why it is better
  - impact or tradeoff
  - whether it is recommended for the current phase

## 5. Open Questions

- List only the unresolved questions that materially block planning, confirmation, or development.

## 6. Recommended Direction

- If there are multiple options, explain the recommended option and why it should be chosen now.

## 7. Customer Confirmation Summary

- Customer confirmed current implementation baseline: pending / yes / not-applicable
- Customer confirmed requirement and scope: pending / yes
- Approved to start development: pending / yes
- Notes from this confirmation round:

## 8. Version Notes

- Date:
- Author:
- Document version:
- Related files:
  - `ai/state/task-intake.md`
  - `ai/state/architecture.md`
  - `ai/state/task-tree.json`
  - `ai/reports/architecture-review.md`
