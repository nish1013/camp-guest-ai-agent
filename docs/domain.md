# Domain: Camp Guest AI Agent

Order and checks: `09-design-order.md` in the playbook. Stories are confirmed before invariants;
invariants are confirmed before the rest is derived.

## Brief

From [`brief.md`](brief.md), verbatim:

> A guest arrives at a holiday camp, reaches their cabin or pitch, and is introduced to **Camp Guest AI Agent**: a 24x7 on-site assistant.
>
> The guest can ask for information, make a request, or raise a complaint. The agent must:
>
> 1. **Understand** what they need and how urgent it is.
> 2. **Triage** - resolve from a camp guide when it can, or hand off when it cannot.
> 3. **Act** - create a ticket and/or call a specialist agent (maintenance, cleaning, restaurant).
> 4. **Keep the guest updated** until the request is done or clearly handed to a human.
>
> Urgent work (leak, no hot water, safety) must jump the queue. Routine work (extra towels, dinner booking) can wait. The agent must not invent camp facts; it uses a guide and tools. It must not pretend a job is finished when it only opened a ticket.

Scope, from the brief's *In v1* column:

- Mobile-friendly web UI (guest + staff views as needed)
- Open intake, no guest login
- Demo adapters + Compose + API key
- Triage + 3 specialists + soft validation + HITL + Pydantic Evals
- Case audit visible in the UI

Settled input: [`brief-review.md`](brief-review.md) F1-F24 and [`decisions.md`](decisions.md).

## User stories

Seed values used below: cabin C12, stay 18-25 Oct, today 19 Oct, booking `BK-48213` for surname
Müller, desk hours 08:00-22:00, guide section `pool-hours` says 08:00-20:00.

### US1: Open the camp page from the cabin QR (guest)

As a guest, I want to scan the QR in my cabin, so that the agent knows my cabin and stay without a login.

| Given | When | Then |
| --- | --- | --- |
| QR token for C12, stay 18-25 Oct | the guest scans it on 19 Oct | page opens with scope C12 + stay. No form. |
| QR token for a stay that ended 17 Oct | the guest scans it | page opens with no scope. Guide answers only until US7 succeeds (D19). |
| token with a bad signature | the guest opens the link | page opens with no scope. The audit records an invalid token. |
| a cookie holds open case K1 | the guest scans again | K1 is shown (D4). |

### US2: Send a message (guest)

As a guest, I want to send a message in my own words, so that I have one place to ask for anything.

| Given | When | Then |
| --- | --- | --- |
| no case cookie | "Where is the pool?" | new case K1. Case link and cookie set. Status "Received". |
| cookie holds open case K1 | "also the heater is off" | the message joins K1. |
| K1 closed 3 hours ago | the guest replies | K1 reopens (D20). |
| K1 closed 25 hours ago | the guest replies | new case K2. |
| the same idempotency key sent twice | client retry | one message, one run (D5). |
| a run on K1 is in progress | a second message arrives | it queues for the next run on K1 (D6). |
| 20 messages from this IP in the last 10 min | a 21st message | refused with "Please try again in a few minutes". No LLM call (D35). |
| none | "No hot water, and book dinner for 2 at 19:30" | two tasks: maintenance and restaurant. Each is routed on its own (D14). |
| none | "my ref is BK-48213, call 07700 900123" | the LLM and the audit see "my ref is [ref], call [phone]" (D3). |
| the LLM fails on every retry | a run | case held for a human. Status "With reception" (D16). |
| none | "it's broken" | one clarifying question. After 2 rounds with no clear answer, held for a human (D32). |

### US3: Ask a question (guest)

As a guest, I want answers from the camp guide, so that I can trust what I am told.

| Given | When | Then |
| --- | --- | --- |
| guide section `pool-hours` | "When does the pool open?" | "08:00-20:00", citing `pool-hours`. No ticket. |
| no guide section on a sauna | "Is there a sauna?" | "I don't have that information", plus the reception number from the guide. No invented fact. |
| the LLM cites `spa-hours`, which does not exist | the answer is checked | the answer is withheld, as if no section matched (D17). |
| no scope | any question | answered. No verification asked. |

### US4: Report a fault or a housekeeping need (guest)

As a guest, I want to report a problem in my cabin, so that the right staff fix it.

| Given | When | Then |
| --- | --- | --- |
| scope C12, stay active | "no hot water" | ticket maintenance / urgent for C12. Status "Logged with maintenance". |
| scope C12 | "can we have extra towels" | ticket housekeeping / can_wait for C12. |
| scope C12 | "heater is off and the tap leaks" | "I found 2 issues: heater off, tap leaking. Correct?" Yes: 2 tickets (D39). |
| scope C12 | "no hot water and the tap leaks" | no confirmation. The urgent fault gets its ticket at once (D39). |
| open heating report from 14:05 in C12, ticket T7 | a second guest in C12: "heater broken" | the LLM says "maybe the same". "Same problem as the 14:05 heating report?" Yes: linked to T7. No: new ticket T9 (D38). |
| open heating report "bedroom heater" in C12 | "lounge heater broken" | the LLM says "different". New ticket. No question (D38). |
| no open report in C12 | two guests report "no hot water" at the same moment | the second report sees the first and gets the "same problem?" question (I4). |
| scope C12 | the LLM proposes `create_ticket(cabin=C14)` | blocked. One reprompt. Still bad: clarify or hold for a human. `TicketPort` is not called (D15). |
| the same idempotency key sent twice | retry | one ticket (D5). |
| no scope | "no hot water" | the step-up form is shown (US7). |

### US5: Ask for a table (guest)

As a guest, I want to ask for a restaurant table, so that I can eat without queuing at reception.

| Given | When | Then |
| --- | --- | --- |
| scope C12, stay active | "table for 4 at 19:30 tonight" | booking request: restaurant, 4, 19:30. Status "Waiting for the restaurant to confirm" (D12). |
| booking request not confirmed | the guest asks "is it booked?" | status unchanged. Never "Booked". |
| no scope | the same request | the step-up form is shown (US7). |
| stay ended, scope has no active stay | the same request | guide answer only, with the restaurant phone number (D19). |

### US6: Report an emergency (guest)

As a guest, I want emergency help at once, so that a real danger is never delayed.

| Given | When | Then |
| --- | --- | --- |
| any scope, or none | "smoke coming from the heater" | fixed emergency guidance from the guide, with phone numbers. Held for a human, urgent, top of the staff view. No verification asked (D8). |
| this IP is over the rate limit | "fire" | handled the same. The limit does not apply. |
| the LLM says spam | "gas smell lol" | the safety rule wins. Held for a human (D13). |
| the LLM is down | "flood in the bathroom" | the guidance is still shown. It needs no LLM. |

### US7: Prove the booking without a QR (guest)

As a guest without the QR, I want to prove my booking, so that I can still make requests.

| Given | When | Then |
| --- | --- | --- |
| no scope, the route needs scope | a request | the run pauses. A form asks for booking surname and booking ref (D2). |
| booking `BK-48213`, surname Müller, stay active | "  muller ", "BK 48213" | match. Scope set. The run resumes. |
| none | wrong ref | "We could not find a booking with those details." |
| cabin hint C12, booking is for C14 | correct surname and ref | the same fixed reply. C14 is never shown (F23). |
| 2 failed attempts on this case | a 3rd fail | case parked. Reception phone shown. No staff work. |
| 3 failed attempts from this IP in the last hour, on other cases | a new attempt | case parked. |
| any | form submitted | surname and ref never reach an LLM or the audit text (D3). |

### US8: Ask for money or a cabin move (guest)

As a guest, I want to ask for a refund, compensation or another cabin, so that staff can decide.

| Given | When | Then |
| --- | --- | --- |
| scope C12 | "I want a refund for last night" | held for a human. Status "Waiting on reception". No ticket, no promise (D36). |
| scope C12 | "can we move to a bigger cabin?" | held for a human. |
| the LLM proposes route `ticket` for a refund | the route is checked | code holds it for a human instead. |

### US9: Follow the case status (guest)

As a guest, I want to see where my request is, so that I do not have to ask again.

| Given | When | Then |
| --- | --- | --- |
| T7 in_progress | the guest opens the case page | "Maintenance is working on it." from a template (D25). |
| case held at 14:00 | the guest opens the case page | "Waiting on reception." |
| case held at 23:10 | the guest opens the case page | "Reception opens at 08:00." (D30) |
| booking confirmed by staff | the guest opens the case page | "Booked: table for 4 at 19:30." |
| the case page is open | the status changes | the page updates without a reload (D22). |

### US10: Send spam or nonsense (sender)

As the camp, I want spam parked, so that it creates no staff work and stays recoverable.

| Given | When | Then |
| --- | --- | --- |
| none | "cheap watches www.example.biz" | verdict spam. Case parked. No ticket, no specialist. The audit records the verdict (D13). |
| none | "asdfgh" | one clarifying question. No ticket. |
| none | spam text containing "fire" | US6 applies. |

### US11: Work the queue (staff)

As staff, I want one sorted list of cases, so that urgent work is done first.

| Given | When | Then |
| --- | --- | --- |
| not logged in | open the staff view | login page (D9). |
| wrong password | log in | refused. |
| urgent, normal and can_wait cases | open the staff view | urgent first, then oldest first (D8). |
| case held at 14:00 | 14:16 | flagged overdue, at the top (D11). |
| case held at 23:10 | 08:15 next day | flagged overdue. Not before (D30). |
| parked cases | open the parked list | each shown with its reason: spam or verification (D13, D2). |

### US12: Resolve a held case (staff)

As staff, I want to approve, edit or reject a held case, so that risky steps get a human decision.

| Given | When | Then |
| --- | --- | --- |
| K3 held for a refund | staff approve | the case continues. Guest status follows the template. |
| K4 held, proposed ticket maintenance / normal | staff change urgency to urgent and approve | ticket created as urgent. |
| K4 held | staff reject | the task is declined. Guest status "Reception has declined this request". |
| any held case | staff try to send free text to the guest | not possible. Only the proposed action can be edited (D31). |
| not logged in | `ResolveAsHuman` is sent | refused (D9). |

### US13: Change a ticket or booking status (staff)

As staff, I want to update a ticket or booking, so that the guest sees real progress.

| Given | When | Then |
| --- | --- | --- |
| T7 open | staff set in_progress | `TicketStatusChanged` is recorded on the case. Guest status "Maintenance is working on it" (D10). |
| K1 has T7 and a confirmed booking | staff set T7 to done | every task is done. K1 closes (D20). |
| booking request | staff confirm | "Booked: table for 4 at 19:30." |
| booking request | staff decline | "The restaurant could not take this booking." |
| T7 linked to K1 and K2 | staff set T7 to done | both cases show done (D7). |

### US14: Restore a parked case (staff)

As staff, I want to restore a parked case, so that a wrong park does not lose a guest.

| Given | When | Then |
| --- | --- | --- |
| K5 parked as spam | staff restore | triage runs again. The spam verdict is overridden (D33). |
| K6 parked after 3 failed verifications | staff confirm the booking by phone, restore, and pick stay C12 | scope set by staff. The run resumes (D33). |

## Invariants

| # | Invariant | Kind | Constraint that keeps it true | Can two requests break it together? |
| --- | --- | --- | --- | --- |
| I1 | A message is stored at most once per idempotency key | immediate | unique key on the idempotency key | yes: a client retry |
| I2 | A case has at most one active run | immediate | run lease on the case row, claimed by a conditional update. No database lock is held during an LLM call (D46) | yes: two messages at once |
| I3 | A ticket is created at most once per case and step | immediate | unique (case, step); `TicketPort.create` is idempotent on it (D5) | yes: a retry or a resumed run |
| **I4** | **Every report in a cabin records the earlier open reports in that cabin it was checked against; none is missing** | immediate | transaction lock on the cabin id while a report is checked and saved (D38) | **yes: the hard one. Two guests in one cabin report at the same moment** |
| I5 | A ticket's or booking request's cabin is its case's scope cabin | immediate | composite foreign key to the case scope | no |
| I6 | Every ticket and booking request has a passing validation record for its step | immediate | written in the same transaction | no |
| I7 | A case scope names its source: QR, step-up or staff | immediate | `CHECK` | no |
| I8 | A parked case has no tickets or booking requests | immediate | case root; version number on the case | yes: a staff restore during a run. The version number rejects the second write |
| I9 | A case flagged safety is urgent and never parked | immediate | `CHECK` | no |
| I10 | A case with 3 failed verifications is parked, unless staff restored it | immediate | case root; version number on the case | yes: as I8 |
| I11 | A closed case has no open task | immediate | case root; version number on the case | yes: a status change during a run. As I8 |
| I12 | A task's status matches its ticket's status | eventual | `TicketStatusChanged` handler (D10, D40) | no |
| I13 | Every routing decision has an audit entry | immediate | written in the same transaction | no |

Not invariants, and where they went:

| Rule | Why it fails the sort test | Goes to |
| --- | --- | --- |
| Overdue flag | derived from held time and desk hours; nothing stored | derive on read (D11, D30) |
| Guest status text | derived from case state | derive on read (D25) |
| No PII in the audit | about what is not stored | policy, D3 |
| Rate limit, failed verifications per IP | about a request | AC on US2, US7 |
| Only staff confirm a booking | precondition | AC on US13 |

## Words used

| Word | Context | Meaning |
| --- | --- | --- |
| Guest | Intake | Person talking to the agent. No login |
| Sender | Intake | Anyone who submits, guest or not (US10) |
| Staff | Intake | Reception or duty manager, behind the staff login (D9) |
| Case | Intake | One conversation with a guest, reached by its case link (D4) |
| Message | Intake | One guest submission, with its idempotency key |
| Task | Intake | One intent of a case: a question, a fault, a table, a money ask, an emergency (D14) |
| Run | Intake | One pass of the graph over a case. At most one at a time (I2) |
| Scope | Intake | The cabin and stay a case may act on, and its source: QR, step-up or staff (I7) |
| Step-up | Intake | Booking surname and ref checked against the stay (D2) |
| Report | Intake | A fault as one guest reported it in one cabin. Checked against earlier open reports (I4) |
| Fault type | Intake | A closed list in config: hot_water, heating, leak, electrics, ..., other |
| Held | Intake | Waiting for a staff decision |
| Overdue | Intake | Held longer than the gate timeout inside desk hours (D30). Derived |
| Parked | Intake | Stopped with no staff work: spam or failed step-up (D2, D13) |
| Safety flag | Intake | Set by the code rule on safety terms (D8) |
| Urgency | Intake | urgent, normal, can_wait |
| Validation record | Intake | Outcome of the arg checks for one step: pass, block, clarify |
| Audit entry | Intake | One routing decision, masked input, tool args, validation outcome (D23) |
| Ticket | Ticketing | One job for staff. Owned by the ticket system |
| Booking request | Intake | A table asked for, waiting for staff to confirm or decline (D12) |
| Cabin, stay, booking ref | Stay | Owned by the booking system |
| Guide section | Guide | A guide entry with a stable id (D17) |
| Desk hours | Intake | Hours reception is staffed. Config (D30) |

## Contexts

| Context | Owns (invariants, words) | Asks | Copies, and why |
| --- | --- | --- | --- |
| Intake (this app) | I1-I13. Case, message, task, run, scope, report, booking request, audit | Stay: step-up and staff restore (D41). Guide: answers (D42). Ticketing: create a ticket (D43) | Stay into scope: a snapshot of the stay at the moment scope is set. Ticket status onto the task: the owner may be down and the page polls often (D40). Emergency guidance and reception number: the guide may be down and an emergency must still be answered (D42) |
| Ticketing (behind `TicketPort`) | Ticket and its status | none | none |
| Stay (behind `StayContextPort`) | Cabin, stay, booking ref, surname | none | none |
| Guide (behind `GuidePort`) | Guide sections | none | none |

Ticketing, Stay and Guide are demo adapters in Compose and the camp's systems in a real deployment.
Booking requests stay in Intake: there is no F&B port in v1 (D12).

## Aggregates and data model

| Aggregate | Root | Context | Identity | Guards invariants | Tables | Guard (key, constraint or version number) |
| --- | --- | --- | --- | --- | --- | --- |
| Case | `Case(case_id)` | Intake | case_id | I2, I3, I5-I11, I13 | `cases`, `tasks`, `validation_records`, `verification_attempts`, `audit_entries` | run lease on `cases` (I2). Version number on `cases` (I8, I10, I11). Unique `(case_id, step_id)` on `tasks` (I3). Composite FK `tasks (case_id, cabin)` to `cases (id, scope_cabin)` (I5). `CHECK` on `cases` (I7, I9) |
| Cabin reports | `CabinReports(cabin_id)` | Intake | cabin_id | I4 | `reports` | transaction lock on the cabin id. Rows are insert-only. Unique `(case_id, step_id)` stops a repeat insert on resume (D44) |

No aggregate:

| Table | Why | Guard |
| --- | --- | --- |
| `messages` | Only I1, over the whole set | unique idempotency key. A message is saved without waiting on a run (D46) |
| `ip_verification_failures` | Request check for D2, no invariant | none |
| `ticket_events` | Outbox for I12 | none |
| `demo_tickets` | The demo `TicketPort` adapter's own store, not Intake's | unique `(case_id, step_id)`: the idempotent create of D5 |
| LangGraph checkpoints | Resume machinery owned by the library (D5) | none |

**Places each fact lives:**

| Fact | Lives in | Copy, and why |
| --- | --- | --- |
| Case scope (cabin, stay dates, source) | `cases` | snapshot of the stay system at the moment scope is set |
| Ticket status | ticket system | copy on `tasks.ticket_status` + `ticket_version` (D40) |
| Ticket ref | `tasks.ticket_ref` | linked tasks hold the same ref. It is a reference, not a copy |
| Report open or closed | derived: report -> task -> ticket status | none |
| Guest status text | derived from case state (D25) | none |
| Overdue | derived from held time and desk hours (D30) | none |
| Booking request and its status | `tasks` | none |
| Routing decision | `audit_entries` | also in the LangGraph checkpoint while a run is live. The checkpoint resumes the run; the audit is the record (D23) |
| Emergency guidance, reception number | guide | copy loaded at start-up (D42) |

**Operation check.** A graph step is the unit of work: each step commits one aggregate (D44).

| Story | Aggregate changed | Result |
| --- | --- | --- |
| US1 open from QR | none. The token sits in the session until the case is created | read only |
| US2 send a message | `messages` (plain), then Case for the run | one aggregate |
| US3, US5, US6, US7, US8, US10, US12, US14 | Case | one |
| US4 report a fault | step 1: Cabin reports (insert the report). Step 2: Case (task and ticket ref) | one per step |
| US9, US11 | none | read only |
| US13 ticket status | ticket system, then `TicketStatusChanged`: one Case per transaction, one per linked task | one per transaction |
| US13 booking status | Case | one |

## Eventual consistency strategy

| Eventual invariant | Strategy | Why |
| --- | --- | --- |
| I12 a task's status matches its ticket's status | in-process handler, outbox polled by the API process | one service, one database. No broker (D45) |

| Event | Committed by | Carries | Handler | Changes |
| --- | --- | --- | --- | --- |
| `TicketStatusChanged` | demo adapter, in the same transaction as the status change. Real adapters: webhook or polling writes the outbox row | ticket_ref, status, version | `ApplyTicketStatus` | one Case per transaction, for each task with that ticket_ref. A version at or below the stored one is ignored |

No inbox table: the version check makes repeats and out-of-order events harmless. An outbox row is
deleted once handled. No broker means no replay window to keep.
