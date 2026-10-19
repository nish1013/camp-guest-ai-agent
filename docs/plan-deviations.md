# Plan deviations

Where the build departs from [plan.md](plan.md), and why. A deviation becomes a decision only once it is added to [decisions.md](decisions.md).

## D1. Integration tests run in CI (PR 2, 2026-10-19)

Plan:     PR series, PR 1: "CI with ruff, mypy and unit tests". Verification lists `make test-int` as a local command.
Built:    CI also runs `make test-int`: Postgres through testcontainers on the GitHub runner's Docker.
Why:      the guards for I1, I2 and I7 are a unique key, a conditional update and a `CHECK`, all in Postgres. The unit tests use no database, so a CI run with unit tests only stays green when any of these guards is removed. Checked by removing each guard: only `tests/integration` fails.
Undo:     delete the `make test-int` step from `.github/workflows/ci.yml`.

## D2. PII is masked when the message is saved (PR 3, 2026-10-19)

Plan:     Request and graph flow: "safety rule (code) -> mask PII -> verify (LLM)", a graph step. Storage: `messages` holds "masked text".
Built:    `SubmitMessage` masks booking refs, emails and phone numbers before the insert. The graph reads the saved, masked text. No mask step in the graph.
Why:      the storage line needs the text masked before it is saved, so raw PII never reaches the database. A graph step would then mask text that is already masked. The safety rule and the rate-limit exemption both run on the masked text, so they agree; the masks never touch a safety term.
Undo:     save the raw text in `SubmitMessage` and add a mask node between `safety` and `verify`.

## D3. Case status columns beyond the storage list (PR 3, 2026-10-19)

Plan:     Storage: `cases` has "safety, state, ..., held_at". The clarify limit is per task (D32).
Built:    `cases` also has `urgency`, `state_reason` and `clarify_rounds`. The clarify count is kept on the case.
Why:      the I9 `CHECK` needs the case urgency on the row; a `CHECK` cannot read `tasks`. The hold reason picks the template: "With reception" after LLM failure (D16), "Waiting on reception" for a money ask (US8). Clarify runs after verify and before split, so no task exists yet to hold the count. A genuine verdict resets it.
Undo:     drop the three columns in a migration; derive urgency from `tasks` and drop the I9 urgency clause.

## D4. An invalid QR token is audited on the next message's case (PR 3, 2026-10-19)

Plan:     US1: "token with a bad signature: page opens with no scope. The audit records an invalid token."
Built:    `GET /q/{token}` logs the bad token and marks the session. The next accepted message writes a `qr_scope: invalid_token` audit entry on the case it creates or joins, in the same transaction as the message. A guest who sends nothing leaves only the log line. A valid scan clears the mark.
Why:      audit entries belong to the Case aggregate and need a case id. At scan time no case exists; the US1 operation check keeps the token in the session until the case is created.
Undo:     drop the session mark and the entry in `SubmitMessage`; the log line stays.

## D5. Emergency guidance comes from config until the guide adapter exists (PR 3, 2026-10-19)

Plan:     US6: "fixed emergency guidance from the guide, with phone numbers". PR 4 copies it from the guide at start-up (D42).
Built:    the guidance is `EMERGENCY_GUIDANCE` in config, shown from the status template.
Why:      PR 3 must pass US6 and has no `GuidePort`. The text is still fixed and needs no LLM, which is what D8 requires.
Undo:     PR 4 replaces the config value with the copy loaded from the guide.
Closed:   PR 4, 2026-10-19. `EMERGENCY_GUIDANCE` is gone from config. The guidance is the guide's `emergency` section, copied at start-up.

## D6. Question tasks hold the guide answer (PR 4, 2026-10-19)

Plan:     Storage: `tasks` has "case_id, step_id, kind, urgency, ..., state". No column holds a guide answer.
Built:    `tasks` also has `answer` and `answer_section`, and a `done` state. A `CHECK` allows an answer only on a question task in state `done`.
Why:      the answer text is written by the LLM (decisions.md, "Guide answer text"), so it cannot be derived on read like a status template. The guest page must show the answer and the section it cites (US3). A question is one task (D14), so its answer belongs on that task's row.
Undo:     drop the two columns and the `done` state in a migration; keep answers in a table of their own keyed by `(case_id, step_id)`.

## D7. A task waiting for scope is saved, not a graph interrupt (PR 5, 2026-10-19)

Plan:     Request and graph flow: "no scope -> step-up form (interrupt)". The run pauses at the route guard and resumes there after the step-up.
Built:    the route guard saves a fault or table task with no scope as `awaiting_scope`, and the run goes on to the next intent. The case page shows the form while such a task waits. A match sets the scope; the next run under the run lease (I2) puts each waiting task through the route guard again. No LLM call is repeated.
Why:      an interrupt pauses the whole run, so a question in the same message waits behind the form. If the step-up then ends in a park, the question is never answered, while US3 answers any question with no scope and D14 routes each task on its own. The waiting task is already saved with its audit entry in one step (I13), so the wait survives a restart with no checkpoint.
Undo:     call `interrupt()` in the route guard for a task with no scope, add the LangGraph Postgres checkpointer, and resume the thread from `POST /c/{case_token}/step-up`.

## D8. A hyphen in the booking ref is ignored like a space (PR 5, 2026-10-19)

Plan:     decisions.md D2: "Ref compare is exact with spaces removed."
Built:    spaces and hyphens are removed from both refs, then the two are compared exactly. Letter case is kept.
Why:      US7 expects "BK 48213" to match `BK-48213`. With only spaces removed, `BK48213` never equals `BK-48213`. A hyphen carries no part of the ref.
Undo:     drop `-` from `_REF_SEPARATORS` in `domain/step_up.py`; the US7 example then needs the hyphen typed.

## D9. A safety case is not parked after 3 failed step-ups (PR 5, 2026-10-19)

Plan:     I10: "A case with 3 failed verifications is parked, unless staff restored it."
Built:    the 3rd failure parks the case, held work included. A case flagged safety stays held. On any case with 3 failures the form is hidden and a further attempt is refused without a booking lookup.
Why:      I9 says a safety case is never parked, and D8 puts safety first. The stored failure count, not the park, is what stops further guessing, so the limit still holds on a safety case.
Undo:     none needed in code; I10 in domain.md would read "unless staff restored it or it is flagged safety".
Closed:   PR 5, 2026-10-19. I10 in domain.md now reads "unless staff restored it or it is flagged safety".

## D10. Confirmations are saved task states, not graph interrupts (PR 6, 2026-10-19)

Plan:     Request and graph flow: "split intents (LLM) -> 2+ faults, none urgent -> confirm split (interrupt)" and "same? (LLM) -> confirm (interrupt)".
Built:    the split check runs after classify and the route guard, over each message's fault tasks. A task waiting for an answer is saved as `awaiting_split` or `awaiting_same`. `POST /c/{case_token}/answer` moves it, and the next run under the run lease (I2) goes on from there. A "no" to the split holds the tasks for a human. `tasks` also has `same_report_id`, the report the guest is asked about.
Why:      fault kind and urgency are known only after classify, so "2+ faults, none urgent" cannot be decided before it. An interrupt pauses the whole run, which D7 already ruled out, and no checkpointer exists to resume one. A wrong split is what D39 guards against, so a "no" goes to a person, not back through the LLM.
Undo:     move the check before classify with an LLM call of its own; add the checkpointer and `interrupt()` as in D7's undo.

## D11. The report step writes no audit entry (PR 6, 2026-10-19)

Plan:     Request and graph flow: "each step: one aggregate, one audit entry (D44, I13)".
Built:    the report step saves only the report, under the cabin lock. The next step, "same problem?", writes the audit entry. It names the report and every report it was checked against.
Why:      audit entries belong to the Case aggregate, the report to CabinReports. One transaction for both breaks D44. The report row is insert-only and holds its own checked-against list, so the step loses no record.
Undo:     write an audit entry in the report transaction, with two aggregates in it.

## D12. Fault types are an enum in code (PR 6, 2026-10-19)

Plan:     domain.md, Words used: "Fault type: A closed list in config".
Built:    `FaultType` in `domain/fault_type.py`. Classify proposes it; a `CHECK` on `tasks` and `reports` holds the same list.
Why:      the LLM output schema carries the list, so the LLM cannot return a type outside it (D15, D48). A list in config would need the schema built at start-up, and no story asks to change the list.
Undo:     move the values to `Settings` and build the classification schema from them at start-up.

## D13. The ticket step holds the case row from the park check to the commit (PR 6, 2026-10-19)

Plan:     domain.md, I8: "case root; version number on the case". The hard part names one lock: the cabin lock for I4.
Built:    after the args pass validation, the ticket step locks the case row (`FOR NO KEY UPDATE`), checks the case is not parked, calls `TicketPort.create`, and saves the ticket in that transaction. The LLM draft runs before the lock.
Why:      the version check alone rejects the ticket row on a parked case, but `create` has already sent the ticket. Every park is an `UPDATE` of the case row, so it now waits for the commit and then loses the version check. A park that commits first is seen before `create`. The lock covers one aggregate and no LLM call, so D44 and D46 hold. The create stays keyed by case and step (I3).
Undo:     drop `lock_case` and save the ticket with the version check alone; a park between `create` and the commit then leaves a ticket sent for a parked case.

## D14. A follow-up on a case in action runs only the safety rule (PR 6, 2026-10-19)

Plan:     US2: "cookie holds open case K1 | 'also the heater is off' | the message joins K1." Request and graph flow: every message goes through verify, split, classify and the route guard.
Built:    a case is in action once one of its tasks has a ticket or a booking request. A new message on such a case runs only the D8 safety rule. It joins the case for staff to read, with a `safety: joined` audit entry: no LLM call, no park, no new task. A case with an open question to the guest (clarify, step-up, split or same-problem) is still triaged, as before. The park step refuses a case in action. The rule is `domain/case_activity.py`, used at the graph entry and in the park step.
Why:      a spam verdict on a follow-up parked a case with an open ticket, against I8; decisions.md D13 parks spam. A safety hit still marks the case urgent and shows the guidance (I9). Chosen on 2026-10-19 in review.
Undo:     drop the entry check in the safety step and the park check; every follow-up is then triaged and a spam verdict can park a case in action.
Closed:   2026-10-19. Added to decisions.md as part of D4 (amended).
