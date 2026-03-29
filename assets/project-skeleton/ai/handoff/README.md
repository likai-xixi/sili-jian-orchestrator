# Handoff Structure

Use per-role handoffs with an active/archive split.

Active peer-agent roles:
- `orchestrator`
- `neige`
- `duchayuan`
- `libu2`
- `hubu`
- `gongbu`
- `bingbu`
- `libu`
- `xingbu`

Rules:
- Put current actionable handoffs under `<role>/active/`
- Move completed or obsolete handoffs to `<role>/archive/`
- Keep `TEMPLATE.md` as the fill-in template for new handoffs
