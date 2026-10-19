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
