# Decisions

## 2026-10-18 — brief review

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D1 | tech | Each cabin/pitch has a QR code. It opens the web UI with a signed token naming the cabin and stay. That token sets the case scope. | **F1.** Scope needs an anchor the guest cannot simply type. Holding the QR means being on site. | Typed cabin number: anyone can claim any cabin. Guest login: against open intake. | Demo seed needs a token per cabin. Tokens are signed with a server key and expire at stay end. |
| D2 | tech | No QR: step-up verification. Routes that need scope pause the graph. A form asks for booking surname and booking ref. Code checks them against `StayContextPort`. A match sets scope and the graph resumes. Any non-match (wrong ref, wrong surname, cabin differs from the hint, stay not active) gets one fixed reply: "We could not find a booking with those details." After 3 fails per case, and per IP in 1 hour, the case is parked and the guest is shown the reception phone number from the guide. | **F1, F23.** Lets a guest off site still act on their stay. The fixed reply leaks nothing. Parking means failed attempts create no staff work. | Surname + arrival date: guessable by people who know the guest. Surname + cabin: both visible on site. Reveal the booking's cabin on mismatch: leaks booking data. Send failed attempts to a human: spam creates staff work. One-time code: deferred, D26. | Surname compare is trimmed, case- and accent-insensitive. Ref compare is exact with spaces removed. Verification applies to this case only. A genuine guest who fails 3 times must call reception. |
| D3 | tech | Surname and booking ref are form fields only and never reach a prompt. Before each LLM call, code masks booking-ref, email and phone patterns in free text. The audit stores the masked text. Guest name from soft context is shown to staff and not used by triage. | **F22.** Verification and triage need no PII in the model. | Send the form fields to the LLM to extract: PII leaves the system for no gain. No masking: free text carries refs and phone numbers to the model. | A surname typed into chat still reaches the LLM. See D29. |
| D4 | tech | A case has a link with a secret token, kept in a cookie. A returning guest with an open case is asked "Add to C12 or new request?". Add joins the case and runs only the safety rule ([plan-deviations D14](plan-deviations.md)). New request opens a new case. A typed case id needs step-up first. Amended 2026-10-19. | **F2.** Without login, a guest needs a way back to the case. The guest names the case, so a follow-up never re-triages a case in action (I8). | New case per message: splits one problem across cases. Match by cabin: joins other guests' cases. Join with no prompt: a spam verdict on a follow-up parks a case with an open ticket. | Losing the cookie and link means starting a new case. One more tap for a returning guest. |
| D5 | tech | `SubmitMessage` takes an idempotency key. The graph uses a LangGraph checkpointer in the DB. `TicketPort.create` takes the key `case_id + step_id`, and adapters must treat a repeat key as the same ticket. | **F3.** A retry or a resumed run must not create a second ticket. | Retry without keys: duplicates. Save the case before calling the port: a crash then loses the ticket reference. | The `TicketPort` contract requires idempotent create. Real adapters must store the key. |
| D6 | tech | One graph run per case at a time. Messages that arrive during a run queue for the next run. | **F4.** Two runs on one case overwrite state. | Merge concurrent results: no safe merge for routes. Reject the second message: loses guest input. | Needs a per-case lock in the case store. |
| D7 | product | A request with the same cabin and category as an open ticket links to that ticket. No new ticket. | **F5.** Staff should see one fault once. | One ticket per case: duplicates for staff. | The second guest gets the first ticket's status. |
| D8 | product | Urgency sets ticket priority and the order of the staff view. A code rule on safety terms (fire, gas, smoke, flood, medical, injury) gives fixed emergency guidance from the guide and goes straight to human. It skips verification and rate-limit parking. | **F6.** A life-safety reply must not depend on an LLM verdict or a verification step. Trade-off: a spammer can use safety words to reach a human. That cost is accepted. A missed real emergency costs more. | LLM decides safety: can miss or delay. Safety after verification: a guest off site with no ref is blocked. Rate-limit safety: an abuser can then lock out a real report. | The LLM can raise urgency but never lower the code rule. Staff will see some false safety alerts. Term list lives in config. |
| D9 | tech | The staff view and `ResolveAsHuman` sit behind a staff login. The demo uses one credential from `.env`. | **F7.** Open intake must not extend to approvals. | Open staff view: anyone approves. Full user management: not needed for v1. | Real deployments supply their own staff auth. |
| D10 | tech | Add a `TicketStatusChanged` event into the case. In the demo, staff change status in the UI. Real adapters send it by webhook or polling. | **F8.** Guest updates need ticket status flowing back. | Guest asks staff directly: breaks "keep the guest updated". | `TicketPort` gains an inbound side. |
| D11 | product | The human gate has a timeout from config. When it passes, the case is flagged overdue in the staff view and the guest sees "waiting on reception". | **F9.** Gives a named state to a human delay. | No timeout: stuck with no signal. Auto-resolve: unsafe for high-stakes paths. | Paging on timeout is deferred, D27. |
| D12 | product | Specialists draft only. They create a ticket or a booking request. The guest sees "confirmed" only after staff confirm. | **F10.** Matches "must not pretend a job is finished". | Specialist confirms bookings: needs an F&B port and trusts the LLM with a side effect. | Restaurant bookings need a staff step. |
| D13 | product | Spam is parked, not deleted, and shown in the staff view. The D8 safety rule overrides a spam verdict. | **F11.** A false positive must stay recoverable. | Delete spam: a genuine case is lost. | Staff view has a parked list. |
| D14 | product | One case per message. Triage splits it into one task per intent. Each task is triaged, validated and routed on its own. | **F12.** "No hot water, and book dinner" needs two lanes. | Two cases: two links for one conversation. First intent only: drops a request. | Case state holds a list of tasks. |
| D15 | tech | Invalid tool args are never rewritten. Block, reprompt the LLM once, then clarify with the guest or go to human. | **F13.** Rewriting changes what the guest asked for without telling them. | Rewrite args in code: silent change. | Brief line 76 "rewrite" is superseded. |
| D16 | tech | LLM errors or timeouts get bounded retries, then the case goes to human with status "with reception". | **F14.** A failure must never drop a case. | Retry forever: case stuck. Fail the request: guest loses the case. | Retry count in config. |
| D17 | tech | A guide answer must cite a guide section, and code checks that section exists. No section means no factual answer. | **F15.** Makes invented facts detectable. | Free answer: untraceable. | Guide content needs stable section IDs. |
| D18 | tech | Rate limits per IP and per cabin token in v1. | **F16.** Every message is an LLM cost. | No limits: cost abuse. | D8 safety messages are exempt. |
| D19 | product | Scope is cabin plus stay dates. A guest with no active stay gets guide answers only. | **F17.** Tickets need a current stay. | Cabin only: past guests act on a cabin. | Pre-arrival questions work. Pre-arrival requests do not. |
| D20 | product | A case closes when all its tasks are done or a human resolves it. A guest reply within 24 hours reopens it. | **F18.** Gives the case an end state. | Never close: inbox grows. Guest closes: guests rarely do. | Reopen window in config. |
| D21 | product | Guest UI is English only in v1. | **F19.** Keeps evals and guide content to one language. | Multilingual: more evals and guide content. | Other languages later. |
| D22 | tech | Guest updates appear on the case page by polling or SSE. `NotificationPort` demo adapter writes case status. | **F20.** The web channel has no push in v1. | Email/SMS: needs contact details and a provider. | Guest must open the page to see updates. Push deferred, D28. |
| D23 | tech | The audit stores decisions, masked inputs, tool args and validation outcomes per node. No retention policy in v1. | **F21.** Enough to explain a run. | Full prompts: duplicates PII risk. | Retention is set by real deployments. |
| D24 | tech | Code decides, the LLM proposes. The ownership table below is binding. | **F24.** Makes each guardrail testable without the model. | Let the LLM decide routing and scope: guardrails become prompts. | Every code-owned step is unit-tested with fake ports. Every LLM step is covered by evals. |
| D25 | product | Guest status text comes from case state through fixed templates. The LLM does not write status. | **F24.** "Must not pretend done" is only enforceable when status follows state. | LLM writes status: can claim done. | Status wording is limited to the templates. |

### Code vs LLM ownership (D24)

| Step | Owner | LLM role |
|---|---|---|
| Rate limit, idempotency key | Code | None |
| Safety-term rule (D8) | Code | None. Can raise urgency, never lower it |
| PII masking (D3) | Code | None |
| Genuine / spam / needs clarification | LLM | Proposes. Code applies the D8 override |
| Intents, category, urgency, route | LLM | Proposes |
| Does the route need scope, pause | Code | None |
| Scope from QR token or step-up form (D1, D2) | Code | None. Never sees form fields |
| Attempt limit, parking (D2) | Code | None |
| Tool args | LLM | Proposes |
| Arg validation: schema, allowed tool, scope (D15) | Code | None |
| Ticket dedup, idempotent create (D5, D7) | Code | None |
| Guide answer text | LLM | Writes. Code checks the citation (D17) |
| Specialist draft | LLM | Drafts. Staff confirm (D12) |
| Human gate timeout (D11) | Code | None |
| Guest status text (D25) | Code | None |

### Deferred to v2

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D26 | tech | One-time code sent to the booking email or phone as a stronger no-QR verification. | **F1.** Strongest fallback, but needs a messaging port. | Not built in v1: D2 covers it. | v1 relies on surname + ref. |
| D27 | product | Page the duty manager when the human gate times out. | **F9.** Needs a paging integration. | v1 flags overdue in the staff view. | Overnight delays depend on staff checking the view. |
| D28 | tech | Push updates to the guest. | **F20.** Needs a push or messaging channel. | v1 uses polling or SSE. | Guest must open the page. |
| D29 | tech | Detect and mask person names in free text before LLM calls. | **F22.** Pattern masking cannot spot names reliably. | v1 masks refs, email and phone only. | A surname typed into chat reaches the LLM in v1. Known limit. |

## 2026-10-19 — user stories

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D30 | product | Desk hours live in config. Inside them, the human gate times out after 15 minutes. Outside them, the guest sees "Reception opens at 08:00" and the clock starts at opening. | The agent is 24x7, the desk is not. A night timeout flags cases nobody will see. | One timeout always on: night cases go overdue for nothing and the guest has no time to expect. A separate night timeout: nobody acts at night either way. | One more status template. Emergencies are unaffected (D8). Refines D11. |
| D31 | product | In `ResolveAsHuman`, staff edit only the proposed action: ticket fields, category, urgency. No free text to the guest. | Guest status comes from templates (D25). | Free-text reply: breaks D25 and needs moderation. | Staff who need to talk to the guest phone them. |
| D32 | product | At most 2 clarifying rounds per task. Then the task is held for a human. | A confused guest must not loop forever. | 1 round: too strict for a vague first message. No limit: a loop with no exit. | The count lives in config. |
| D33 | product | Staff can restore a parked case of either kind: spam or failed verification. A restore after failed verification sets the scope by hand. | Staff can check a guest by phone. The park must stay recoverable (D13). | Restore spam parks only: a real guest who failed 3 times is stuck. | Scope gains a third source: staff, beside QR and step-up. |
| D34 | product | No guest cancel in v1. A guest who wants to cancel says so in a message. Staff cancel it. | Keeps the story set small. A cancel is rare. | A cancel button: another story and another state change from an untrusted client. | Cancels go through staff (US13). |
| D35 | tech | Rate limit 20 messages per 10 minutes, per IP and per cabin token. Values in config. | Gives D18 numbers. A real guest rarely sends more. | 5 per 10 min: blocks a guest in a long exchange. No limit: cost abuse. | Safety messages are exempt (D8). |
| D36 | product | Refund, compensation, cabin move and safety close-out are always held for a human. Code checks the route, not the LLM. | The brief: no irreversible change without a human when stakes are high. | Let the LLM judge stakes: a prompt is not a guardrail (D24). | The list lives in config. |
| D37 | product | Ticket states: open, in_progress, done, cancelled. A booking request adds confirmed and declined. | Enough to drive every status template. | More states, such as on_hold: no story needs them. | Real adapters map their states onto these. |

## 2026-10-19 — invariants

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D38 | product | One ticket per job. A report links to an open ticket only when the guest confirms "same problem". The LLM proposes the match. A lock on the cabin row orders the reports in a cabin. Refines D7. | Same cabin and category is not the same job: two heaters in one cabin are two jobs. Only a person can tell. | Link on cabin + category: merges unrelated jobs. Link on cabin + fault type: two heaters still merge. Fault type + item list: every cabin needs an item list, vague reports still mismatch. Always new, staff flag duplicates: duplicates reach staff. | One extra question when an open report may match. The lock is held for the check and insert only, never while the guest answers. Different cabins never wait on each other. |
| D39 | product | When a message holds 2 or more faults, the guest confirms the split before tickets are created. Urgent and safety faults skip the confirmation. | One job is one ticket. A wrong split sends the wrong staff. | Create at once, guest corrects by reply: wrong tickets reach staff first. Confirm always: delays urgent work. | One extra question for multi-fault messages. Refines D14. |
| D40 | tech | Ticket status is copied onto the task by the `TicketStatusChanged` handler. The guest page reads the copy. | The ticket system may be external and down. The page polls often (D22). Case close (D20) needs every task's status. | Ask `TicketPort` on every page load: many calls into the camp's system, and the page breaks when it is down. | The copy can lag by seconds. The handler must ignore repeats and out-of-order events. |

## 2026-10-19 — domain model

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D41 | tech | Intake asks Stay for step-up and staff restore. When Stay is down, the guest sees "We cannot check bookings right now. Please call reception on ..." and the attempt does not count towards the 3. | Step-up needs current booking data. It is rare, so asking is cheap. | Copy all bookings into Intake: a second copy of PII, and a sync to keep it current. | Step-up depends on Stay's uptime. QR guests are not affected. |
| D42 | tech | Intake asks Guide for answers. Emergency guidance and the reception number are copied at start-up. When Guide is down, a question gets "I can't check the guide right now", plus the copied reception number. | An emergency reply must never depend on another system (D8). | Ask for everything: an emergency fails with the guide. Copy the whole guide: a sync for no gain. | A guide change to the emergency section needs a restart to take effect. |
| D43 | tech | Intake asks Ticketing to create a ticket. When Ticketing is down, bounded retries, then the task is held for a human, "With reception". | Creating a ticket is a command. It cannot be copied. | Queue tickets locally and replay: a second ticket store to keep consistent. | Ticket creation depends on Ticketing's uptime. Same path as D16. |
| D44 | tech | One graph step commits one aggregate. US4 saves the report in one step and the task's ticket in the next. | One aggregate per transaction. The checkpointer resumes from the last committed step (D5). | Save the report and the task together: two aggregates in one transaction, one lock waits on another. | A crash between the steps resumes at step 2. The report's unique `(case_id, step_id)` stops a second insert. |
| D45 | tech | I12 uses an in-process handler on an outbox. The handler ignores a version at or below the stored one. No inbox. No broker. | One service, one database. A version makes repeats and out-of-order events harmless. | Broker: an extra service for one event. Inbox table: duplicates the version check and needs a cleanup cron. | Real ticket adapters must send a version or an updated-at that increases. |
| D46 | tech | I2 uses a run lease on the case row, claimed by a conditional update and expiring after a set time. Messages are saved without the lease. | A database lock held during an LLM call blocks for seconds. A message must never wait on a run (D6). | Row lock for the whole run: long locks, a blocked message intake. | A crashed run frees the case when its lease expires. Lease length in config. |

## 2026-10-19 — plan

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D47 | tech | Server-rendered UI: FastAPI + Jinja + HTMX. Status by SSE. | One deployable and no Node build keep "clone, compose, one key". Plain HTML works on a phone. | React SPA: a second build and a JSON API for one small UI. | UI interactions are limited to what HTMX does well. Enough for forms and a live status line. |
| D48 | tech | `LlmPort` uses Pydantic AI with the OpenAI provider. The model name comes from `.env`. | Output is parsed into Pydantic models, which D15 needs. The provider is config, not code. | Raw OpenAI SDK: hand-written parsing. LangChain chat models: a second abstraction beside LangGraph. | One `OPENAI_API_KEY` runs the demo. |
| D49 | tech | Evals run only by hand, `make evals`. Not in CI. | Evals cost tokens and depend on the model. CI stays free and deterministic. | Evals in CI with a secret key: cost on every push and flaky runs. | Run evals before merging a change to a prompt or the graph. |
| D50 | tech | Postgres 16. | I4 needs a transaction lock on the cabin id. LangGraph has a Postgres checkpointer. | SQLite: no advisory lock, weak concurrent writes. | Compose runs a Postgres service. Integration tests use testcontainers. |
| D51 | product | A new request offers quick picks with free text: Maintenance, Cleaning, Restaurant, Question, Reception. The pick is a hint to the LLM. The route guard decides (D36). | Guided intake gives context at the start. Fixflo, Duve and HiJiffy use picks. | Free text only: less context on a vague first message. Pick as the route: "Question" on a refund skips the D36 hold. | The audit stores the pick next to the LLM category. |
