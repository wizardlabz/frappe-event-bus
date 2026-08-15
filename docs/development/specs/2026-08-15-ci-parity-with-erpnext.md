# CI and Badge Parity with frappe/erpnext

**Status:** assessment, awaiting decision
**Date:** 2026-08-15
**Question:** what does [frappe/erpnext](https://github.com/frappe/erpnext) do for testing and badges, and what should this project adopt?

---

## 1. What erpnext actually has

### Workflows

Read from the ERPNext v15 checkout installed on the development bench — thirteen workflows:

| Workflow | Purpose |
|---|---|
| `server-tests-mariadb.yml` | Main suite, **4-container parallel matrix** via an external orchestrator |
| `server-tests-postgres.yml` | Same suite against **PostgreSQL** |
| `server-tests-mariadb-faux.yml`, `patch_faux.yml` | Stand-ins so required checks resolve when the real job is skipped |
| `linters.yml` | pre-commit **plus [semgrep](https://semgrep.dev) with `frappe/semgrep-rules`** |
| `semantic-commits.yml` | **commitlint** enforcing Conventional Commits on every PR |
| `patch.yml` | Migrations applied against an older database |
| `release.yml`, `release_notes.yml` | Release and release-note automation |
| `docs-checker.yml`, `labeller.yml`, `label-base-on-title.yml`, `docker-release.yml` | Project housekeeping |

### Badges

The **live** README carries three:

1. Learn on Frappe School
2. CI → `server-tests-mariadb.yml`
3. docker pulls → Docker Hub

The v15 checkout's README carries five — the same CI and docker pulls, plus **UI tests**, **codetriage**, and **codecov**. Those three were dropped upstream between v15 and the current branch.

That matters for this assessment: **adding a codecov badge would not make us more like erpnext today.** It would make us like erpnext two versions ago. Coverage may still be worth having on its own merits, but not as a parity argument.

## 2. What this project has

| | Core | Provider |
|---|---|---|
| Server tests | ✅ real Frappe stack, MariaDB + Redis | ✅ same, **plus a live RabbitMQ broker** |
| pre-commit linter | ✅ ruff, prettier, eslint | ✅ |
| Badges | CI, Linter, GPLv3 | CI, Linter, GPLv3 |
| Test count | 83 | 29 |
| Suite runtime | ~8s | ~3s |

The foundation matches erpnext's: a real framework, real database, no mocking at the framework layer. Two things we already do that erpnext does not — a live message broker in CI, and integration tests that deliberately **fail rather than skip** when the broker is missing.

## 3. Gap analysis

### Worth adopting

**Semantic commits (commitlint)** — high value, ~30 lines, no infrastructure.

The project already adopted Conventional Commits as policy, but nothing enforces it. This closes the gap between a stated convention and a checked one, and it directly feeds `RELEASE_NOTES.md`: notes are only as easy to assemble as the commit history is disciplined.

```yaml
- run: npm install @commitlint/cli @commitlint/config-conventional
- run: npx commitlint --verbose --from ${{ github.event.pull_request.base.sha }} \
                                 --to ${{ github.event.pull_request.head.sha }}
```

**Semgrep with `frappe/semgrep-rules`** — high value, and pointed at a weakness this project has already demonstrated.

Frappe publishes rules covering SQL injection in `frappe.db.sql`, unsafe `frappe.safe_eval` use, and **missing permission checks on whitelisted methods**. This project shipped five unguarded whitelisted endpoints and caught them by hand. A linter that catches that class automatically is worth more here than the average project, because both raw SQL and whitelisted endpoints appear in the codebase.

```yaml
- run: git clone --depth 1 https://github.com/frappe/semgrep-rules.git frappe-semgrep-rules
- run: pip install semgrep
- run: semgrep ci --config ./frappe-semgrep-rules/rules --config r/python.lang.correctness
```

**PostgreSQL matrix** — medium value, and it would find a real bug today.

The atomic outbox claim uses MySQL backtick quoting:

```sql
UPDATE `tabEvent Bus Outbox Message`
SET status = 'Publishing'
WHERE name = %s AND status IN ('Pending', 'Retry Scheduled')
```

PostgreSQL rejects backtick identifiers. **The app cannot currently run on a Postgres site**, and nothing in CI would tell us. The consumer's claim statement is specified the same way, so the problem would double rather than stay contained.

Two responses, and they are not exclusive: add a Postgres job, or rewrite the claim through Frappe's query builder so it is portable by construction. The query builder is arguably the better fix — it removes the raw SQL entirely — but only a Postgres job proves it.

### Not worth adopting

**Parallel test matrix with an external orchestrator.** ERPNext splits across four containers because its suite is enormous. Ours runs in eight seconds. This would add orchestration for no gain.

**codecov.** Dropped from erpnext's own README, so it carries no parity argument. Coverage reporting may be worth adding later on its own merits; it is not a parity item.

**`*-faux` workflows.** These exist to satisfy required status checks when the real job is skipped by path filters. We have no path filters and no required-check configuration yet.

**docker-release, labeller, docs-checker, codetriage.** Project-scale housekeeping for a repository with far more contributors and issue traffic.

### Deferred

**`patch.yml`** — tests that migrations apply cleanly against an older database. The app has no patches yet, so there is nothing to test. This becomes relevant the moment the first schema migration ships, which the consumer work in v0.3 will produce.

**`release_notes.yml`** — automated release notes. Now that `RELEASE_NOTES.md` exists and is maintained by hand, automation is premature; revisit once there are several releases to compare against.

## 4. Recommendation

Three changes, applied to **both** repositories:

| Change | Cost | Why now |
|---|---|---|
| Add `semantic-commits.yml` | ~30 lines, seconds of CI | Enforces a convention already adopted |
| Add semgrep to `linters.yml` | ~4 lines, ~1 min of CI | Catches the exact bug class already found by hand |
| Add a Postgres job to `ci.yml` | one matrix entry, ~2.5 min | Would fail today, which is the point |

Expect the Postgres job to fail on its first run. That failure is the deliverable — it converts an unknown portability assumption into a known, tracked bug.

Badges stay as they are. The current three (CI, Linter, GPLv3) already exceed what erpnext's live README shows, and a Postgres matrix strengthens the existing CI badge rather than needing one of its own.

## 5. Open decision

Whether to fix the backtick portability problem by adding a Postgres job first and letting it fail, or by rewriting the claim statements through the query builder before the job lands.

Recommendation: **add the job first.** A failing check documents the bug precisely and proves the fix when it goes green. Fixing first and adding the job afterwards leaves no evidence the job actually detects anything.
