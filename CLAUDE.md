# Market Scanner — Claude Fleet & Token-Optimization Execution Rules

## Architecture & Fleet Orchestration

This workspace uses a multi-tier delegation model to minimize cloud token usage. Cloud frontier models are reserved for governance, solutioning, and evaluation. Routine code synthesis, refactoring, tests, and system tasks run offline on local models through the `tokenfrugal` MCP gateway.

Claude acts strictly as the **Lead Architect & Orchestrator**. Direct cloud token generation for routine code, tests, docstrings, and boilerplate is forbidden. Cloud models must never output raw application code, complete migration files, or large shell scripts directly into the chat buffer.

### Priority: tokenfrugal first, Haiku as tracker and instructor

- **tokenfrugal is the first priority.** Every routine code, test, refactor, DDL, docstring, script, or log-triage task goes to `tokenfrugal.dispatch_task` before anything else. Claude does not write that work itself, even when it looks small.
- **Haiku (`claude-haiku-4-5`) remains the task tracker and instructor for tokenfrugal.** Haiku keeps the plan status, writes the isolated task specs and acceptance criteria that tokenfrugal receives, reviews each reply, and sends diff-only corrections back. Sonnet and Opus do not take over that role.
- Haiku's fallback role applies only after the tokenfrugal rules in Section 2 fail.

---

## 1. Fleet Routing Matrix

| Tier / Role | Assigned Model | Interface | Mandatory Scope & Invariants |
| :--- | :--- | :--- | :--- |
| **Solutioning & Deep Arch** | `claude-opus-5-5` | Cloud Native | ADRs, interface schemas (OpenAPI/Protobuf), domain modeling, technical arbitration. Never writes implementation code or touches filesystem tools. |
| **Project Management & Orchestration** | `claude-sonnet-5-5` | Cloud Native / `claude-swarm` | Milestone tracking, splitting ADRs into single-function task tickets, git PR governance, agent handoffs, circuit-breaker escalations. |
| **QA & Lead Engineer** | `claude-haiku-4-5` | Cloud Native + `tokenfrugal` | Pre-flight test specs, isolated context extraction, prompts for local models, test output validation, local model supervision, Haiku fallback. |
| **Local Builder** | Chosen by tokenfrugal | `tokenfrugal.dispatch_task` (builder role) | Code, single-function implementations, refactors, tests, DDL migrations, fixtures, docstrings, file edits via allowlisted MCP tools. |
| **Local Thinker** | Chosen by tokenfrugal | `tokenfrugal.dispatch_task` (thinker role) | Debugging, review, log and terminal triage into compact JSON, summaries, planning notes. |

Local model selection belongs entirely to tokenfrugal. Claude never names a local model in a task, plan, or prompt. It only chooses the role (builder or thinker) by passing an agent slug.

### Task Routing

| Task | Route | On failure |
| :--- | :--- | :--- |
| Code, single function, refactor, tests, fixtures, DDL, docstrings, file edits | tokenfrugal builder | `resume_task` once → re-scope smaller → Haiku fallback |
| Debugging, code review, failure log triage, summaries, planning notes | tokenfrugal thinker | `resume_task` once → Haiku fallback |
| Browser or database validation | tokenfrugal role whose profile has those tools; Haiku if none fits | Haiku fallback |
| System, config, and PowerShell/Bash scripts | tokenfrugal builder (scripts), thinker (triage) | Haiku fallback |
| Test specs, payload pruning | Haiku (Stage 3) | n/a |
| ADRs, interface schemas, arbitration | Opus, no delegation | n/a |
| Ticket decomposition, PR governance, circuit-breaker one-shot fix | Sonnet, no delegation | n/a |

---

## 2. Multi-Agent Task Execution Lifecycle

Every modification, feature, and bug fix proceeds through this five-stage pipeline:

```
[Stage 1: Opus]         High-level ADR, interface schemas, behavioral contracts
│
▼
[Stage 2: Sonnet]       Task ticket decomposition (scoped to 1 function or 1 file)
│
▼
[Stage 3: Haiku]        Unit test spec authoring & payload pruning (AST symbol bounds only)
│
▼
[Stage 4: Local LLM]    Offline execution via tokenfrugal (builder / thinker roles)
│
▼
[Stage 5: Verification] Local test run; failure triage via thinker; Haiku reviews the summary
│
├──> [Pass]               ──> Git commit & stage marked complete
├──> [Fail (cycle ≤ 2)]   ──> Haiku sends a diff-only correction back to the builder
└──> [Fail (cycle > 2)]   ──> Circuit breaker escalates a minimal payload to Sonnet for a one-shot fix
```

### Stage Details & Delegation Protocols

1. **Stage 1: Solutioning (Opus)**
   * Outputs declarative contracts, class interfaces, and state transition requirements.
   * Prohibited from emitting boilerplate, scaffolding, or raw script blocks.

2. **Stage 2: Orchestration (Sonnet)**
   * Decomposes the spec into isolated, single-unit tasks. Multi-step work is registered first with `plan_add`.
   * Routes code work to the tokenfrugal builder role and system ops, config, or log triage to the thinker role, per the Task Routing table.

3. **Stage 3: Test Formulation & Payload Pruning (Haiku)**
   * Authors test specs and expected assertions *before* implementation.
   * Resolves target ranges with `synaptree` (`search_graph` / `search_code`).
   * Full file reads are prohibited. Haiku isolates only the target signature, immediate type definitions, and acceptance criteria.

4. **Stage 4: Offline Execution (`tokenfrugal`)**
   * Find the agent slug with `list_roles`, then dispatch. Pass only the slug and task; do not pass a model:
     ```
     dispatch_task(agent="<engineering-... slug>", task="<isolated signature, types, paths, and acceptance criteria>", plan_id=<N if planned>)
     ```
   * Pass file paths in the workspace, not pasted files. Local models have a 16k–32k context.
   * Replies are capped summaries. Call `get_detail(task_id)` only when the full output is needed.
   * On failure: call `resume_task(task_id)` once, then re-scope the task smaller.
   * Use `ask_followup` only when a builder or thinker needs a clarification to continue.

5. **Stage 5: Verification & Circuit Breaker**
   * Run the project's test command after every delegated change. Never accept delegated code unrun.
   * If a test run fails, raw logs are never pasted into chat. Triage them through the thinker role via `dispatch_task`.
   * Haiku reviews the summary. If under the 2-cycle threshold, Haiku dispatches a diff-only correction to the builder.
   * **Two-Strike Circuit Breaker**: if two consecutive local cycles fail, the minimal error payload escalates to `claude-sonnet-5-5` for an authoritative one-shot fix.
   * Mark plan tasks `done` only with evidence: a real git SHA or a finished gateway task ID.

### Haiku Fallback

If `tokenfrugal` does not deliver quality execution, delegate the same task to a Haiku subagent (`claude-haiku-4-5`, e.g. `Agent` with `model: "haiku"`) instead of writing it on the orchestrator model. Failure cases that trigger the fallback:

* A "done" report with no file change.
* Failing tests after the delegated change.
* Wrong or partial output.
* Any failure that persists after one `resume_task` plus one re-scope.

Verify the fallback result the same way (`git status` / `git diff`, run the tests), and state in the report that the fallback was used.

---

## 3. Tool & Gateway Execution Policies

Claude connects to no external container tools directly. Tool access runs through the `tokenfrugal` gateway. Each role maps to a model, a Docker MCP profile, and 4–6 allowlisted tools, defined in `gateway/personas.yaml` (inspect with `list_roles`). Gateway tools: `dispatch_task`, `ask_followup`, `get_detail`, `resume_task`, `list_roles`, `plan_add`, `plan_overview`, `plan_revert`, `plan_update_from`.

Browser validation and database inspection go through a role whose profile exposes those tools. If no role covers the task, Haiku runs it.

### Codebase Intelligence (`synaptree-mcp`)

Unbounded file reads, raw directory walks, or shell dumps (`cat`, `type`, large greps) are prohibited. Delegated builder and thinker roles also receive `synaptree` as a native server.

* **Index Health**: run `synaptree.index_status()`. If stale or missing, run `synaptree.index_repository()` from the main checkout, never a worktree. Re-index after merges.
* **Symbol Resolution**: `search_graph` / `search_code`, `trace_path` (callers, callees, references), `query_graph` (Cypher; hierarchy via `INHERITS` / `IMPLEMENTS` edges), `get_code_snippet`.
* **Targeted Reading**: read a file directly only after the symbol's line range is pinpointed, or for configs and docs the index excludes.

### Output Guardrails

* **Log Limiting**: Docker and system execution queries must truncate output (`--tail 50` or `Select-Object -First 50`).
* **Database Telemetry**: use targeted schema inspection and projection queries (never `SELECT *`), with `LIMIT 25`.

---

## 4. Operational Invariants & Local Environment Setup

* **Token Protection**: any cloud response with more than 50 lines of boilerplate application code or raw configuration is an invariant violation. Delegate it through `tokenfrugal`.
* **Local Ollama Environment**: enable Flash Attention and quantized KV caching so 32k contexts fit in dedicated GPU memory:
  ```powershell
  $env:OLLAMA_FLASH_ATTENTION = "1"
  $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
  ```

---

## 5. Operational Guardrails

- Commits have the human author only: no Co-Authored-By trailer, no "generated with" footer.
* **Zero Direct Cloud Code**: Sonnet and Opus produce architecture definitions, pseudocode, and task tickets. Implementation goes through `tokenfrugal`.
* **System Administration Tasks**: OS configuration, PowerShell/Bash scripting, dependency installs, and port checks are dispatched to the builder role. Log triage goes to the thinker role. Cloud models do not generate these directly. Ask before installing software.
* **Model Selection**: tokenfrugal picks the local model for each role. Do not hardcode or override model names in Claude's prompts, plans, or the gateway config from this repo.
* **Secrets**: never paste secrets into tasks or chat. Keep them in the gateway's secret store (`~/.docker/mcp/mcp.env`).
* **Verification Commands**:
  * Offline tests: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`
  * Local infra bindings: load `../Shared-Market-Research-Infra/secrets/market_scanner.env` with `INFRA_LOCAL=1`.

> NOTE: local-model routing is defined by the tokenfrugal gateway and `~/.claude/CLAUDE.md`. Ignore the legacy `cc-token-saver` profiles and older model tiers if they appear elsewhere.
## Code intelligence (synaptree-mcp)

Repo: https://github.com/maxh8086/synaptree-mcp (MCP server `synaptree`, local checkout at `SYNAPTREE_DIR`, project name `SYNAPTREE_PROJECT`, default `tokenfrugal`). Query the code graph before grepping or reading whole files.

- Check `index_status(project)` first; if stale or missing, run `index_repository(project, root_path)` with the main checkout path, not a worktree.
- Find code: `search_graph` / `search_code`. Callers, callees, references: `trace_path`. Structure: `get_architecture`. Hierarchy: `query_graph` (Cypher over `INHERITS` / `IMPLEMENTS` edges). Read one symbol: `get_code_snippet`.
- Read files directly only after the symbol is located, or for configs, docs and files the index excludes.
- Delegated roles builder, analyzer, reviewer and debugger get `synaptree` as a native server; the Router injects `project` automatically.
- Re-index after merges.


