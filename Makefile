.PHONY: install dev dev-backend dev-frontend test test-backend test-frontend gen-api check-contract e2e

install:
	cd backend && uv sync
	cd frontend && pnpm install --frozen-lockfile

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uv run python manage.py migrate --no-input && uv run python manage.py runserver 8000

dev-frontend:
	cd frontend && pnpm dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && pnpm test --run && pnpm typecheck

# Export the OpenAPI doc straight from the NinjaAPI object (no server needed), then
# generate TypeScript types from it. See docs/ARCHITECT_MEMO.md A15.
gen-api:
	cd backend && uv run python manage.py export_openapi_schema --api tracker.api.api --output ../frontend/openapi.json --indent 2
	cd frontend && pnpm gen:api

check-contract: gen-api
	git diff --exit-code frontend/src/api/schema.d.ts

e2e:
	cd frontend && pnpm e2e
