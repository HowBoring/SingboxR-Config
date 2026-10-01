# Fix: `empty inline rule-set`

Affected build: the initial Windows single-file packaging in V1.1.

## Symptom

```text
initialize router: parse rule-set[2]: empty inline rule-set
```

## Cause

The project intentionally kept several local override rule-sets as editable placeholders. They were valid JSON source files but contained an empty `rules` array. The Windows packer converts local rule-sets to `type: inline`, and reF1nd rejects an inline rule-set with no rules.

## Fix

The placeholder rule-sets now contain one inert exact-domain rule under the reserved `.invalid` TLD. This keeps every rule-set non-empty without matching normal traffic, while preserving the stable override tags:

- `local-ai-extra`
- `local-direct`
- `local-proxy`
- `local-reject`
- `local-realip`

Replace the `rules` array in the corresponding `rules/local/*.json` file when you add your own overrides.

After updating, rebuild the Windows profile:

```powershell
py -3 scripts/build.py windows
```

If you have a target reF1nd core available, validate it as well:

```powershell
py -3 scripts/build.py windows --check --core .\bin\sing-box.exe
```
