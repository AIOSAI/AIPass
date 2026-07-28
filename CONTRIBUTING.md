# Contributing to AIPass

AIPass is in beta, built by a solo developer working with an AI team. Contributions are welcome.

## Before You Start

Open an issue first. Use the [issue templates](https://github.com/AIOSAI/AIPass/issues/new/choose) for bug reports or general feedback. This lets us discuss scope and approach before you write code.

## Pull Requests

PRs are welcome after an issue has been discussed. Keep changes focused -- one fix or feature per PR. Include tests where applicable.

**Target the `dev` branch.** `main` only receives tested release trains from `dev` -- all work integrates on `dev` first (full test suite + standards audit), then rides a dev-to-main merge. GitHub defaults new PRs to `main`; switch the base to `dev` when you open one. If you forget, we'll retarget it -- your PR stays open either way.

Changes under `src/aipass/spawn/templates/` also need the template registry regenerated (`drone @spawn regenerate-registry`) -- the registry tracks a content hash per template file and will report drift otherwise.

## Development

- Python 3.10+
- Tests: `pytest` (4,900+ tests across the project)
- Quality: AIPass uses its own standards system ([seedgo](src/aipass/seedgo/README.md)) for automated audits
- Run `./aipass install --no-init` to bootstrap the full environment (contributors work in the engine repo itself — no first-project scaffold needed)

## Questions?

Open a [feedback issue](https://github.com/AIOSAI/AIPass/issues/new?template=feedback.yml) or start a discussion in an existing thread.
