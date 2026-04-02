# Doc Coverage Gate v3.1.1

Use this policy when project docs exist in mixed formats (md/mdx/rst/adoc/wiki) and feature coverage must not drift.

## Core rules

1. Parse all supported doc formats into a unified IR (`version`, `repo_id`, `source_format`, `doc_path`, `line_range`, `anchor`, `feature_refs`, `metadata`).
2. Feature Registry must include hard evidence:
   - `api_paths[]`
   - `config_keys[]`
   - `db_objects[]`
   - `code_anchors[]`
3. Risk handling:
   - High risk: block (strict)
   - Medium risk: conditional block with 48h arbitration (natural time; if crossing holidays, extend to next business day end)
   - Low risk: warn + limited pass
4. Shadow → Strict only when all hold:
   - observation >= 14 days
   - high-risk miss = 0
   - coverage >= 95%
   - false-positive <= 5%
   - audit completeness = 100%

## Degrade and rollback

- Single adapter failure: switch to full-warning mode.
- Adapter failure rate threshold (default):
  - daily failure rate > 10%, or
  - any rolling 1-hour failure rate > 30%
  Then auto-downgrade to shadow and alert.

Registry unavailable matrix:

- low risk: fail-open (warn + audit)
- medium/high risk: strict protective block

Rollback triggers:
- strict-stage miss rate > 1%
- consecutive high-risk false decisions >= 3
- audit chain interruption

## Audit requirements

Append-only decision log with:
- timestamp, operator, repo_id, feature_id, risk_level, gate_mode, decision
- rule_version, evidence_hash, report_path, override_reason

Override requires dual sign-off (security + deploy owner), with explanation archived within 6 hours.
