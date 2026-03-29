# Approval Policy

## Review Roles

- libu2
- hubu
- gongbu
- bingbu
- libu
- xingbu

## Final Audit

- Do not allow commit or release without final audit.

## Conflict Handling

1. record the conflict
2. get written responses
3. escalate unresolved conflicts to final audit

## Review Loop Limits

- Default review limit before cabinet replan: 4
- Default review limit after cabinet replan: 2
- Configure these limits in `ai/state/review-controls.json`

## Customer Decision Path

- If review still fails after the post-cabinet limit, stop internal review loops.
- Generate a customer decision report.
- Wait for an explicit customer decision before resuming, pausing, or terminating the batch.
