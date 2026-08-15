# Contributing

## Setup

Clone into a Frappe v15 bench and install the pre-commit hook:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/wizardlabz/frappe-event-bus --branch main
bench --site <your-site> install-app frappe_event_bus

cd apps/frappe_event_bus
pre-commit install
```

**Install the hook before your first commit.** CI runs the same pre-commit configuration, so unformatted code fails the Linter workflow. This is by far the most common reason a pull request goes red.

## Linting

```bash
pre-commit run --all-files
```

The configuration runs `ruff` (import sorting, linting, formatting), `prettier`, and `eslint`, plus whitespace, AST, JSON, TOML, and YAML checks. Built assets under `public/dist/` are gitignored and excluded.

## Tests

```bash
bench --site <your-site> set-config allow_tests true
bench --site <your-site> run-tests --app frappe_event_bus
```

CI provisions a real Frappe stack — MariaDB and Redis service containers, `bench init`, `bench new-site`, `bench install-app` — and runs the same command. Nothing is mocked at the framework layer, so tests exercise real doctypes, real link validation, and real transactions.

### Writing tests

Two conventions the existing suite follows, both learned from CI failures:

**Do not depend on ERPNext.** CI installs Frappe alone. A test referencing an ERPNext doctype passes on a developer bench and fails in CI. If you need a submittable doctype, note that Frappe core ships none — build your own fixture, as `tests/test_event_types.py` does. Remember a DocType name must start with a letter, so the `_Test` prefix used for test *records* is not valid for a doctype.

**Do not depend on site state.** `Event Bus Settings.enabled` defaults to `0`, so any test expecting outbox rows must enable the bus itself. A test that relies on your bench already having it enabled will fail on a fresh site.

Creating a DocType is DDL, which commits implicitly and escapes `FrappeTestCase`'s per-test rollback. Build such fixtures in `setUpClass` and remove them in `tearDownClass`.

## Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add destination priority
fix: stop the worker double-claiming a message
docs: document the retry backoff formula
test: cover the on_cancel lifecycle event
refactor: extract backoff into a pure function
style: apply ruff-format
ci: run the linter on pull requests
```

Write the body to explain *why*, not *what* — the diff already shows what changed.

## Pull requests

1. Branch from `main`.
2. Keep the change focused; separate mechanical reformatting from behavioural change so reviewers can read the diff.
3. Ensure `pre-commit run --all-files` and the test suite pass locally.
4. Open the PR and confirm both CI checks are green before requesting review.

## Project layout

```
frappe_event_bus/
  rule_engine.py          document events → outbox rows
  rendering.py            Jinja rendering + JSON Schema subset
  template_builder.py     field tree and template generation
  api.py                  whitelisted endpoints
  providers/
    interface.py          EventBusProvider + result contract
    registry.py           event_bus_providers hook resolution
  publisher/
    outbox_worker.py      claiming, publishing, status transitions
    backoff.py            pure exponential backoff
    retry.py              scheduled entry point
    replay.py             replay endpoint
    retention.py          scheduled purge
  frappe_event_bus/doctype/   the six doctypes
  tests/
```

Pure logic is deliberately kept free of database coupling — `rendering.py` and `backoff.py` are unit-testable without a site, and should stay that way.

## Documentation

`docs/` is user-facing. Internal notes and drafts belong in `_local/`, which is gitignored.

Documentation describes **what the code does**, not what the plan intends. Where a planned capability does not exist, say so explicitly rather than describing it in the present tense.
