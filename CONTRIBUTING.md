# Contributing to Skilluv

Thanks for your interest in contributing to Skilluv. This document explains how to participate.

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code. Report unacceptable behavior to the maintainers.

## How to contribute

### Reporting bugs

- Search existing issues first
- Use the "Bug report" issue template
- Include: environment, reproduction steps, expected vs actual behavior, logs if relevant

### Proposing features

- Open a "Feature request" issue first — discuss before coding
- Explain the use case, not just the solution
- Larger features may require a design discussion before a PR is accepted

### Submitting code

1. Fork the repository
2. Create a branch: `git checkout -b feature/short-description` or `fix/short-description`
3. Make your changes with clear commits (see commit conventions below)
4. Ensure tests pass locally
5. Update documentation if you change behavior
6. Push to your fork and open a pull request
7. Fill the PR template completely

## Commit conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description

- feat: new feature
- fix: bug fix
- docs: documentation only
- refactor: no behavior change
- test: tests only
- chore: tooling, build, dependencies
- perf: performance improvement
- ci: CI changes
```

Example: `feat(auth): add magic link expiration configuration`

## Pull request expectations

- **One logical change per PR** — do not bundle unrelated fixes
- **Tests required** for new features and bug fixes
- **CI must pass** before review
- **Discussion in issues before large changes** — avoid surprise refactors
- **AI-assisted contributions are welcome and encouraged** — disclose the assistance level in the PR description (see AI Policy below)

## AI policy

Skilluv is AI-friendly. You may use Copilot, Cursor, Claude, ChatGPT, or any other AI tool to write, review, or refactor code. We only ask that you:

- **Verify** the code works as intended — you own the PR
- **Disclose** significant AI assistance in the PR description (a single sentence is enough)
- **Refactor** AI-generated code so it fits the project's style and is maintainable
- **Never** paste secrets, private keys, or proprietary data into an AI prompt

## Development setup

See the `README.md` for local setup instructions.

## Style guidelines

Language-specific style is enforced by CI:
- Rust: `cargo fmt` + `cargo clippy` (strict)
- TypeScript/Svelte: `prettier` + `eslint`
- Python: `ruff` + `black`

Run these locally before pushing.

## Communication

- **GitHub Discussions** for questions and ideas
- **GitHub Issues** for bugs and concrete feature requests
- **Discord** (link in README) for real-time chat
- Please be patient — this is a small maintainer team

## Licensing

By submitting a contribution, you agree that your work is licensed under the same license as the project (see `LICENSE`). No CLA is required.

## Recognition

Contributors are listed automatically via GitHub. Significant contributors may be highlighted in release notes.

Merci pour ta contribution !
