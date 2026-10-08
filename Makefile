# ygg-atlas quality gate. `make check` must be green before any PR (see ARCHITECTURE.md).
# PNPM can be overridden, e.g. `make check PNPM=pnpm` where pnpm is installed globally.
PNPM ?= COREPACK_INTEGRITY_KEYS=0 corepack pnpm

.PHONY: check check-backend check-frontend format format-backend format-frontend audit audit-backend audit-frontend install hooks

check: check-backend check-frontend ## Run every gate (backend + frontend)

check-backend: ## Format check, lint, types, architecture contracts, tests + coverage
	cd backend && uv run ruff format --check . ../evals
	cd backend && uv run ruff check . ../evals
	cd backend && uv run pyright && uv run pyright ../evals
	cd backend && uv run lint-imports
	cd backend && uv run pytest --cov=app -q

check-frontend: ## Prettier check, ESLint, tsc, Vitest, production build
	cd frontend && $(PNPM) -s check

format: format-backend format-frontend ## Auto-format and auto-fix everything

format-backend:
	cd backend && uv run ruff format . ../evals && uv run ruff check --fix . ../evals

format-frontend:
	cd frontend && $(PNPM) -s format

audit: audit-backend audit-frontend ## Dependency vulnerability scans (also run in CI)

audit-backend: ## Expected red on an x86_64 macOS toolchain: see ARCHITECTURE.md §6
	cd backend && tmp=$$(mktemp) && trap 'rm -f "$$tmp"' EXIT \
		&& uv export --no-dev --no-hashes --no-emit-project --format requirements-txt \
		| uv run python scripts/locked_requirements.py > "$$tmp" \
		&& uvx pip-audit -r "$$tmp" --disable-pip --no-deps

audit-frontend:
	cd frontend && $(PNPM) audit --prod --audit-level high

install: ## Install backend + frontend dependencies
	cd backend && uv sync
	cd frontend && $(PNPM) install --frozen-lockfile

hooks: ## Install the git pre-commit hooks
	uvx pre-commit install
