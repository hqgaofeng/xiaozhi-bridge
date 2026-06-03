# Contributing to xiaozhi-bridge

First off, thanks for taking the time to contribute! 🎉

## Code of Conduct

This project is a personal learning project. Be kind, be helpful, and assume good faith.

## How to Contribute

### Reporting Bugs

Open a [Bug Report](../../issues/new?template=bug.md) with:
- Clear reproduction steps
- Expected vs actual behavior
- Environment info (OS, Docker version, etc.)
- Relevant logs

### Suggesting Features

Open a [Feature Request](../../issues/new?template=feature.md) explaining:
- The problem you're trying to solve
- Your proposed solution
- Alternatives you considered
- Priority level

### Submitting Pull Requests

1. **Fork the repo** and create a branch from `main`:
   ```bash
   git checkout -b feature/amazing-thing
   ```

2. **Make your changes** following our conventions:
   - Python: `ruff` + `mypy` clean
   - TypeScript: `pnpm type-check` clean
   - Add tests for new features
   - Update docs

3. **Run tests locally**:
   ```bash
   # Python
   cd bridge && uv run pytest

   # Web
   cd web && pnpm build
   ```

4. **Write a good commit message**:
   ```
   feat(bridge): add Aliyun ASR provider

   - Add asr/aliyun.py with @register_asr decorator
   - Update config docs with Aliyun-specific options
   - Add tests for AliyunASR

   Fixes #42
   ```

5. **Push and open a PR**:
   ```bash
   git push origin feature/amazing-thing
   ```
   Then open a PR on GitHub and fill in the template.

## Coding Conventions

### Python

- Python 3.12+
- Use `uv` for dependency management
- Type hints everywhere (use `mypy --strict` for new modules)
- Docstrings on public functions (Google style)
- Tests with `pytest` (asyncio_mode=auto)
- Follow the 4-step Plan → Implement → Self-review → Refine workflow

### TypeScript

- TypeScript strict mode
- React 18 + functional components
- Tailwind CSS for styling
- Use shadcn/ui-style primitives
- No class components (legacy)

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `style:` — formatting, no code change
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or fixing tests
- `chore:` — build, CI, deps

## Architecture Principles

1. **Pluggable** — ASR / TTS / LLM all use abstract base + registry
2. **Documented** — every public API has a docstring
3. **Tested** — new features come with tests
4. **Type-safe** — strict typing in Python and TypeScript
5. **Self-reflective** — use the Plan → Implement → Self-review → Refine loop

## Project Structure

```
xiaozhi-bridge/
├── bridge/         # Python WebSocket bridge
├── web/            # React admin console
├── docs/           # Documentation
├── deploy/         # Deployment configs
├── config/         # Config examples
├── Dockerfile.*    # Docker images
└── docker-compose*.yml
```

When in doubt, look at the existing code in each module.

## Release Process

1. Update `docs/changelog.md` with your changes
2. Bump version in `bridge/pyproject.toml` and `web/package.json`
3. Commit: `git commit -am "chore: release v0.2.0"`
4. Tag: `git tag -a v0.2.0 -m "v0.2.0"`
5. Push: `git push origin main --tags`
6. CI builds and publishes Docker images to ghcr.io
7. Create a GitHub release with the changelog

## Questions?

Open an issue or reach out to the maintainers. We try to respond within a few days.
