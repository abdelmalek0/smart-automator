# AGENTS.md

## Project

Python/FastAPI backend, Vite React dashboard, and a C Connect app (secondary). The API runs as systemd unit `smart-automator.service`.
Setup: README.md.

## Commands

- Install: `uv sync`
- Add a Python dependency: `uv add <package>`
- Tests: `uv run pytest`
- Run a Python script: `uv run script.py`
- UI tests: `cd ui && npm test`
- After `ui/` changes, run: `cd ui && npm run build` (the service serves `ui/dist`)
- After backend changes, restart the app: `systemctl restart smart-automator.service`

Never use pip, system Python, or root `main.py`. 

## Design

- Prefer a general solution; treat the current site or task as one instance, not the spec.
- Prefer the smallest change that fully solves the problem.

## Code Style

- Python 3.12. Match surrounding style.
- Prefer async APIs.
- Use type hints
- Keep functions small and focused.

## Testing

- Add tests for new behavior.
- Run the tests that cover your change.
- Do not weaken or delete tests just to make them pass.

## Docs

- Update docs only when it's needed.

## Git

- Commit only when asked.
- Suggest a `fix:` / `feat:` / `refactor:` message for each plan, and a PR title for each PR.
