# Contributing

Thanks for helping. Ham radio software gets better when operators with
different radios pitch in.

The complete rules are in [AGENTS.md](AGENTS.md). They apply to humans and AI
agents alike. In short:

1. **Start from an issue.** Bug reports, feature requests, and radio support
   requests are welcome at any time.
2. **Plan before you code.** Implementation work needs an issue with a
   software plan (the **Implementation task** template) that the maintainer
   approves with the `plan-approved` label.
3. **Keep it small.** One concern per issue. Aim for about 300 lines and 5
   files or fewer (see AGENTS.md, Task sizing).
4. **Branch** from `dev` as `issue-<n>-<slug>`, and **open a PR to `dev`** with
   `Closes #<n>`. `master` changes only through release PRs.
5. **Test.** Unit tests for everything, no radio required. Run the full
   regression before you open the PR.
6. **Mind the licenses.** This project is GPL-3.0-only. Record any code
   adapted from wfview or elsewhere in [THIRD_PARTY.md](THIRD_PARTY.md).

## Have a radio we don't support?

The most useful contribution is a short scope capture from your radio, plus
notes on what the radio showed at the time (frequency, span, scope mode).
Open a **Radio support request** and see
[docs/adding-a-radio.md](docs/adding-a-radio.md).

## Development quick start

```bash
uv sync
git config core.hooksPath .githooks
uv run pytest --cov
uv run ruff check . && uv run ruff format --check . && uv run mypy
sh tests/hooks/run.sh
```

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
