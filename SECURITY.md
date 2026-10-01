# Security

## Secrets and subscription URLs

Do not commit real airport/provider subscription URLs, node credentials, or generated Windows profiles.

The repository intentionally ignores:

- `private/*` except `private/.gitkeep`
- `dist/*` except `dist/.gitkeep`
- runtime state under `state/*`
- local sing-box binaries under `bin/*`

Use the files under `examples/` as templates. Run `python scripts/manage.py init` locally to create private configuration files, then fill them only on your own machine.

If a credential is committed accidentally, remove it from Git history and rotate/revoke it at the provider immediately. Merely deleting it in a later commit is not sufficient.

## Reporting issues

For configuration bugs that do not contain private credentials, open a normal GitHub issue. Do not paste subscription URLs, node passwords, access tokens, API secrets, or private logs into public issues.
