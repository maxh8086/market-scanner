# Readiness review 3: collector-split-spec.md (single lens: implementation readiness)

Saved by the orchestrator from the reviewer's hand-back (the reviewer agent is read-only). Spec text only; the reviewer did not read the repo code. The spec was not edited.

## Verdict per task
- S0: DISPATCHABLE (conditional). Needs postgres MCP for run times; its portfolio/crosscheck items are decisions, gate on user review.
- S1a: BLOCKED. Missing: events-source marker, Fastify base-URL config name, file of the run writer and `get_last_runs`, `--request-id` flag, test files, how the advisory lock is held.
- S1b: BLOCKED. `config/collector_services.json` schema undefined (list or map, fields); file paths of `split_registered` and `first_run.tick`.
- S2a: BLOCKED. No DDL or columns (depends on S0), migration number unassigned, no must-not-change list, too large for one small-model task without the S0 list.
- S2: BLOCKED. No DDL or columns, backoff rule "to be tuned", location of shared code and callers to wire unnamed, depends on S1a for the `skipped` writer (edge missing).
- S5a: BLOCKED. Missing edges on S1b and S2; migration number, watchdog token path and delivery to the server, vectors and test paths, `slot` vs `catchup` rule, manual request vs retry gap and cooldown, manual-mode sources, cron library choice.
- S5b: DISPATCHABLE (conditional). Status route path is deferred to the task; two test runners (server and ui-v2).
- S3: BLOCKED. No server Dockerfile or build, bind change not tied to a file, server env and DB credentials, `SERVER_PORT` value, mounts for the services file and token, contradicts M10 ("same mounts and secrets"), acceptance is three checks.
- S4: BLOCKED. Package path not chosen, token file, launcher, `collector_runtime.json` format, `ui` health path, log size, compose project and file path, `--request-id`, Task Scheduler registration.
- S6: BLOCKED. Acceptance not a command; missing edge on S1b; exact edit unspecified.
- S7: BLOCKED. Fundamentals queue built by no task; bundles two moves; acceptance observational.
- S8: BLOCKED. Needs the freshness spec; migration number; acceptance not a command; S7 dependency looks unnecessary; Mongo env for three services built by no task.
- S9: BLOCKED. Vectors file path, files to edit, acceptance needs an explicit grep or test.

## Depends check
Acyclic. Missing edges: S5a on S1b and S2; S2 on S1a; S6 on S1b.

## Contracts (4.5a)
Enough for a fake API except: `request_id` type, `slot` vs `catchup`, behaviour of a pending request inside a retry gap or cooldown, how a request is marked claimed, no contract for the events-source token or the events endpoints.

## Contradictions
- M4 text (`pending_request`) is stale against 4.5a (`reason: "request"`).
- M3 says S0 acceptance includes back-fill; S0 does not list it.
- M10 vs S3 "same mounts and secrets".
- 4.2 `docker compose run --rm <service>` vs M15 form (`--profile collectors run --rm --no-deps --name collector-<source>`).
- Section 2 item 1 (home-events sources and reconciler split) has no S-task; M9 defers them to the filings spec plan.
- Duplicate 4.6 heading; section 7 step 4 still asks for this re-review.

## Relied on but built by no task
Watchdog token provisioning, events-source token, Fastify Dockerfile and build, fundamentals queue and staleness data, `ui` health path, Task Scheduler registration, `collector_runtime.json` values, events-source marker mechanism, migration numbers beyond 047.

## Blockers
1. S2 and S2a have no DDL.
2. Missing Depends edges.
3. S3 lacks server Dockerfile, env, mounts, port, token.
4. S4 lacks package path, token path, runtime-config format, `ui` health path.
5. S1a/S1b lack events marker, base-URL config, `--request-id`, services-file schema.
6. Fundamentals queue built by no task.
7. S6-S9 acceptance not commands.
8. Migration number collisions (047 for S2, S2a, S5a).

## Minors
S5b two runners; M4 stale; M10 not in S3; S7 bundles two moves; S8 lists S7 needlessly; duplicate 4.6 heading; `slot` vs `catchup` undefined; manual-mode due rule unstated; home-events sources have no task.
