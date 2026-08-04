# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Wiki application split into two main modules. `wiki-web/` is the Next.js frontend, with route handlers in `app/api/`, pages in `app/`, shared UI in `components/`, helpers in `lib/`, types in `types/`, and static assets in `public/`. `wiki-backend/` is the FastAPI backend, with application code in `app/`, API routers in `app/api/v1/`, core configuration in `app/core/`, and AnythingLLM/Postgres/RustFS services under `anythingllm/`. Use `start_wiki.sh` from the repository root to manage the full local stack.

## Build, Test, and Development Commands

- `./start_wiki.sh start`: starts Docker services, FastAPI, and Next.js.
- `./start_wiki.sh status`: checks managed service state.
- `./start_wiki.sh logs`: shows recent backend/frontend logs.
- `cd wiki-web && npm run dev`: runs the frontend on port 3000.
- `cd wiki-web && npm run build`: builds the production frontend.
- `cd wiki-web && npm run lint`: runs ESLint.
- `cd wiki-backend && uv run uvicorn app.main:app --reload`: runs the backend directly.

Always use `uv run <script>.py` for backend Python scripts. Add missing Python dependencies with `uv add <package>`.

## Coding Style & Naming Conventions

Frontend code uses TypeScript, React, Next.js App Router, Ant Design, and 4-space indentation. Name React components in `PascalCase`, hooks/helpers in `camelCase`, and route files according to Next.js conventions such as `route.ts` and `page.tsx`. Backend code uses Python 3.10+, FastAPI, SQLAlchemy, Pydantic, and snake_case module/function names. Keep comments concise and write new code comments in Chinese when explaining non-obvious logic.

## Testing Guidelines

The project currently has limited formal test coverage. For frontend changes, run `npm run lint` and `npm run build`. For backend changes, add focused Python tests near the affected module or under a future `tests/` directory, then run them with `uv run pytest`. Name tests `test_<feature>.py` and keep fixtures local unless shared setup is clearly needed.

## Commit & Pull Request Guidelines

Recent commits use short messages such as `bugfix`, `fix name issue`, and `feat: wire chatbot and sync custwiki theme`. Prefer the clearer conventional form: `feat: ...`, `fix: ...`, `docs: ...`, or `chore: ...`. Pull requests should include a short summary, commands run, affected frontend/backend areas, linked issues when applicable, and screenshots or screen recordings for UI changes.

## Security & Configuration Tips

Keep secrets in ignored `.env` files. Do not expose `ADMIN_TOKEN`, `ANYTHINGLLM_API_KEY`, database credentials, or S3 credentials in committed files. AnythingLLM and storage services are intended to bind to `127.0.0.1` for local development.
