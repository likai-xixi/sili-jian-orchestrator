# Resource Dependency Policies

This runbook tracks missing real-world dependencies such as API keys, live service access, test accounts, permissions, and hardware.

## Policy Modes

- `block`: stop autonomous execution immediately until the dependency is supplied.
- `mock`: keep building with mocks or stubs, then require a real-world retest before the configured gate.
- `skip`: intentionally leave the dependency unresolved for now, but keep the debt visible and require a real-world retest before the configured gate.

## Typical Usage

Configure the defaults:

```bash
python ai/tools/resource_requirements.py configure-policy <project-root> --default-policy mock --credential-policy mock --real-api-policy mock --account-policy skip
```

Record a missing dependency:

```bash
python ai/tools/resource_requirements.py record-gap <project-root> --resource-name "Stripe live API key" --category credential --policy mock --due-stage release --scope-level module --scope-label payments --notes "Use sandbox stubs until release gate."
```

Mark the dependency as supplied:

```bash
python ai/tools/resource_requirements.py resolve-gap <project-root> --gap-id stripe-live-api-key-... --summary "Customer provided the live key in the vault." --supplied-by customer
```

Close the real-world retest after it passes:

```bash
python ai/tools/resource_requirements.py complete-retest <project-root> --gap-id stripe-live-api-key-... --outcome pass --summary "Release-gate payment callback retest passed with the live key."
```

## Runtime Behavior

- Any open `block` gap freezes autonomous execution immediately.
- Any `mock` or `skip` gap remains visible in `ai/reports/resource-gap-report.md`.
- When the configured gate is reached, unresolved `mock` or `skip` gaps become user-input blockers.
- Final gates stay closed until the real-world retest debt is cleared.
