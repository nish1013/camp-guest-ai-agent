# Plan: Camp Guest AI Agent, a 24x7 guest assistant for a holiday camp

One Python app: FastAPI serves a phone-first web UI and runs a LangGraph triage graph over ports.
Docker Compose runs it with Postgres and demo adapters. One OpenAI API key is the only secret.

Status: locked, 2026-10-19

## Context

**The brief.** [`brief.md`](brief.md). Stories, invariants and the model: [`domain.md`](domain.md). Diagrams: [`architecture.md`](architecture.md).
Every choice: [`decisions.md`](decisions.md), D1-D50.

**Owner's decisions (2026-10-19):**
1. Server-rendered UI: Jinja + HTMX, SSE for status (D47).
2. OpenAI through Pydantic AI. Model from `.env` (D48).
3. Evals run only when triggered by hand. Not in CI (D49).
4. Postgres (D50).

**Facts checked read-only:** the repo holds docs only. No code, no CI.

## Stack

| Concern | Choice | One-line reason |
| --- | --- | --- |
| Language | Python 3.12 | LangGraph, Pydantic and Pydantic Evals are Python |
| Packages | uv | one lock file, fast installs in Docker |
| HTTP | FastAPI | Pydantic models at the edge, SSE support |
| UI | Jinja + HTMX | no Node build; plain HTML works on a phone (D47) |
| Graph | LangGraph + Postgres checkpointer | branches and interrupts; resume after a crash (D5) |
| LLM | Pydantic AI, OpenAI provider | output parsed into Pydantic models (D15, D48) |
| Database | Postgres 16, SQLAlchemy Core, Alembic | transaction lock for I4, checkpointer (D50) |
| Tests | pytest, testcontainers-postgres | concurrency tests need a real Postgres |
| Evals | Pydantic Evals, `make evals` | by hand only (D49) |
| Lint, types | ruff, mypy --strict | in CI |

## Request and graph flow

```
POST /messages -> save message (I1) -> claim run lease (I2) -> graph
graph:
  safety rule (code) --hit--> emergency reply + hold
  mask PII -> verify (LLM) --spam--> park | --unclear--> clarify (max 2)
  split intents (LLM) -> 2+ faults, none urgent -> confirm split (interrupt)
  per task: classify (LLM) -> route guard (code: D36 list, needs scope?)
     question -> guide answer (LLM) -> citation check (code)
     fault    -> save report (CabinReports) -> same? (LLM) -> confirm (interrupt)
                 -> specialist args (LLM) -> validate (code) -> TicketPort.create
     table    -> restaurant args (LLM) -> validate (code) -> booking request
     money    -> hold
     no scope -> step-up form (interrupt)
  each step: one aggregate, one audit entry (D44, I13)
```

## Endpoints

| Method, path | Story | Does |
| --- | --- | --- |
| `GET /q/{qr_token}` | US1 | checks the signature, keeps the scope token in the session, renders the page |
| `GET /` | US2 | page with no scope |
| `POST /messages` | US2 | `SubmitMessage`: text, idempotency key, optional cabin hint and name |
| `GET /c/{case_token}` | US9 | case page |
| `GET /c/{case_token}/events` | US9 | SSE status stream |
| `POST /c/{case_token}/answer` | US4 | answer to a confirm question: split, same problem |
| `POST /c/{case_token}/step-up` | US7 | surname and booking ref |
| `GET,POST /staff/login`, `POST /staff/logout` | US11 | one credential from `.env` (D9) |
| `GET /staff/cases`, `/staff/cases/parked`, `/staff/cases/{id}` | US11 | queue, parked list, case audit |
| `POST /staff/cases/{id}/resolve` | US12 | approve, edit action, reject |
| `POST /staff/cases/{id}/restore` | US14 | optional stay id after failed step-up |
| `POST /staff/tickets/{ref}/status` | US13 | demo ticket status, writes the outbox |
| `POST /staff/bookings/{task_id}/status` | US13 | confirm or decline |

## Validation and responses

| Status | When |
| --- | --- |
| 200 | a repeat idempotency key: the first result, nothing new (I1) |
| 404 | unknown or forged case token. The same reply for both |
| 409 | a staff action loses the version check (I8, I10, I11). The UI reloads the case |
| 422 | empty message, over 2,000 chars, or a malformed form |
| 429 | rate limit (D35). Never for a safety hit (D8) |
| 303 to login | any `/staff` path without a session |

A failed step-up is a 200 with the one fixed reply (D2). The status code must not leak the reason.

## Storage

```
cases               id, case_token, scope_cabin, scope_stay_from/to, scope_source, safety,
                    state, run_lease_until, version, held_at, closed_at
tasks               case_id, step_id, kind, urgency, fault_type, ticket_ref, ticket_status,
                    ticket_version, booking fields, state      unique (case_id, step_id)
validation_records  case_id, step_id, outcome, args
verification_attempts, audit_entries                 per case
reports             cabin_id, fault_type, case_id, step_id, checked_against[]   insert-only
messages            idempotency_key unique, case_id, masked text
ip_verification_failures, ticket_events (outbox), demo_tickets, checkpoints
```

## The hard part

- **The failure.** Two guests in C12 report "no hot water" at the same moment. Both see no open
  report, and two tickets send two technicians to one boiler.
- **The guard.** `pg_advisory_xact_lock(cabin_id)` around "read open reports, insert report" (I4).
  It is held for milliseconds, never while the guest answers.
- **Why not simpler.** A unique key on (cabin, fault type) merges two heaters into one job (D38). A row
  lock on `cases` serialises the wrong thing: the two reports are on different cases.

## Tests

Unit tests run the graph against fake ports and a fake `LlmPort`. Integration tests use real Postgres
and the demo adapters. Every "yes" row in the invariants has a test that fails without its guard.

| Test | Covers | Fails when |
| --- | --- | --- |
| two `POST /messages` with one key, in parallel | I1 | the unique key is dropped |
| two runs claim one case | I2 | the lease update is unconditional |
| crash after `TicketPort.create`, resume | I3, D5 | the create key is not `(case, step)` |
| two reports in C12 in parallel threads | I4 | the advisory lock is removed |
| task for C14 on a C12 case | I5 | the composite FK is dropped |
| ticket with a blocked validation | I6 | the record is not checked |
| staff park during a run that creates a ticket | I8 | the version check is skipped |
| safety hit plus LLM "spam" | I9, D8 | the code rule runs after the LLM |
| 3rd failed step-up, then 4th | I10, D2 | the count is per request, not stored |
| last task done closes, a reply within 24h reopens | I11, D20 | close ignores an open task |
| status events v3, v2, v3 | I12, D45 | the version is not compared |
| every node writes one audit entry | I13 | a node skips the audit |
| LLM proposes `cabin=C14` | US4, D15 | validation passes args through |
| `BK-48213`, phone and email in text | D3 | the masker misses a pattern |
| guide cites a missing section | US3, D17 | the citation is not checked |
| held at 23:10, overdue at 08:15 | D30 | the clock ignores desk hours |

**Evals** (`tests/evals`, `make evals`, by hand): spam, safety words, cross-cabin args, two-intent
split, "same problem" match, one happy path per specialist lane, one guide answer.

## PR series

Each PR is from fresh `main` and green in CI before the next starts.

1. **`chore/project-setup`**: uv project, Dockerfile, Compose (api + Postgres), Alembic, `/health`,
   CI with ruff, mypy and unit tests.
   **Accept when:** `docker compose up` gives `GET /health` 200 with the DB checked; CI fails on a type error.
2. **`feat/case-intake`**: `cases`, `messages`, `SubmitMessage`, case token cookie, QR token, run lease,
   rate limit, fixed status templates. The graph is a stub that replies "Received".
   **Accept when:** the I1, I2 and I7 tests pass and fail with their guard removed; US1 and US2 rows for
   new case, join, retry and 429 pass.
3. **`feat/triage-graph`**: `LlmPort` with Pydantic AI, PII masking, safety rule, verify, park,
   clarify limit, split, classify, route guard, LLM retries to hold, audit.
   **Accept when:** US6, US8 and US10 pass on a fake LLM; the I9 and I13 tests pass.
4. **`feat/guide-answers`**: `GuidePort` demo on `data/camp-guide.md`, citation check, emergency copy
   at start-up.
   **Accept when:** US3 passes; with the guide adapter raising, US6 still shows the guidance.
5. **`feat/step-up`**: `StayContextPort` demo with seed stays, step-up form, attempt limits, parking.
   **Accept when:** US7 passes; I10 passes; surname and ref appear in no LLM call and no audit row.
6. **`feat/fault-tickets`**: `reports`, advisory lock, "same problem" and split confirmations,
   maintenance and cleaning specialists, validation records, idempotent demo `TicketPort`.
   **Accept when:** US4 passes; I3, I4, I5, I6 and I8 pass and fail with their guard removed.
7. **`feat/restaurant-booking`**: restaurant specialist, booking request task.
   **Accept when:** US5 passes; status never reads "Booked" before staff confirm.
8. **`feat/staff-view`**: login, queue, overdue, parked list, resolve, restore, ticket and booking
   status, outbox handler, case close and reopen.
   **Accept when:** US11-US14 pass; I11 and I12 pass; a staff action during a run gets 409.
9. **`feat/guest-status-page`**: case page, SSE, every status template, desk hours.
   **Accept when:** US9 passes on a 375 px viewport with no horizontal scroll.
10. **`feat/evals`**: Pydantic Evals datasets and `make evals`.
    **Accept when:** `make evals` with a key passes every case; a planted cross-cabin arg fails it.
11. **`docs/readme`**: README with the demo walk-through and how to write a real adapter.
    **Accept when:** a clean clone, `cp .env.example .env`, a key, and `docker compose up` run the
    walk-through with no other step.

## Verification

```
make lint           ruff + mypy --strict
make test           unit, fake ports, no network
make test-int       Postgres via testcontainers, demo adapters
make evals          by hand, needs OPENAI_API_KEY
docker compose up   then the README walk-through
```

## Deviations

None yet.
