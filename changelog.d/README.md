# Changelog fragments

Every PR into `dev` adds **one small file here** instead of editing
`CHANGELOG.md` (#45). This keeps parallel PRs from conflicting.

- Name: `<issue>.<type>.md`, for example `30.added.md`. For a second entry
  on the same issue, use `30.added.2.md`.
- Types (Keep a Changelog): `added`, `changed`, `deprecated`, `removed`,
  `fixed`, `security`.
- Content: one line in plain language for an operator, without the issue
  number (it is added automatically). Example: `UDP remote control (off by
  default) and the \`ctl\` command.`
- PRs with nothing user-visible (CI-only, refactors) can use the
  `no-changelog` label instead.

Preview the unreleased section:

```
python scripts/build_changelog.py --preview
```

The release PR folds the fragments into `CHANGELOG.md` and deletes them:

```
python scripts/build_changelog.py --version 0.2.0
```
