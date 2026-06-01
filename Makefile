.PHONY: dev test lint docker clean format check

# ── Development ───────────────────────────────────────────────────────────────

dev:
	uvicorn api.server:app --reload --port 8000

dev-web:
	cd web && npm run dev

dev-all:
	$(MAKE) -j2 dev dev-web

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	python3 -m pytest tests/ -v

test-unit:
	python3 -m pytest tests/unit/ -v

test-integration:
	python3 -m pytest tests/integration/ -v

test-cov:
	python3 -m pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html:htmlcov

test-watch:
	python3 -m pytest_watch -- tests/unit/ -v

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	ruff check api/ core/ db/ agents/ tools/ config/

format:
	ruff format api/ core/ db/ agents/ tools/ config/

check: lint
	mypy api/ core/ db/ agents/ tools/ --ignore-missing-imports --no-strict-optional

# ── Docker ────────────────────────────────────────────────────────────────────

docker:
	docker-compose up --build

docker-test:
	docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit

docker-mfe:
	docker-compose --profile mfe up --build

docker-down:
	docker-compose down

# ── Utilities ─────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf htmlcov .coverage .mypy_cache .ruff_cache

seed:
	python3 scripts/seed.py

migrate:
	python3 -c "import asyncio; from db.migrations import run_migrations; asyncio.run(run_migrations())"
