# Decisions

## 2026-10-18 — brief review

| # | Kind | Decision | Why | Alternatives considered | Consequence |
|---|---|---|---|---|---|
| D1 | tech | Each cabin/pitch has a QR code. It opens the web UI with a signed token naming the cabin and stay. That token sets the case scope. | **F1.** Scope needs an anchor the guest cannot simply type. Holding the QR means being on site. | Typed cabin number: anyone can claim any cabin. Guest login: against open intake. | Demo seed needs a token per cabin. Tokens are signed with a server key and expire at stay end. |
| D2 | tech | No QR: step-up verification. Routes that need scope pause the graph. A form asks for booking surname and booking ref. Code checks them against `StayContextPort`. A match sets scope and the graph resumes. Any non-match (wrong ref, wrong surname, cabin differs from the hint, stay not active) gets one fixed reply: "We could not find a booking with those details." After 3 fails per case, and per IP in 1 hour, the case is parked and the guest is shown the reception phone number from the guide. | **F1, F23.** Lets a guest off site still act on their stay. The fixed reply leaks nothing. Parking means failed attempts create no staff work. | Surname + arrival date: guessable by people who know the guest. Surname + cabin: both visible on site. Reveal the booking's cabin on mismatch: leaks booking data. Send failed attempts to a human: spam creates staff work. One-time code: deferred, D26. | Surname compare is trimmed, case- and accent-insensitive. Ref compare is exact with spaces removed. Verification applies to this case only. A genuine guest who fails 3 times must call reception. |
| D3 | tech | Surname and booking ref are form fields only and never reach a prompt. Before each LLM call, code masks booking-ref, email and phone patterns in free text. The audit stores the masked text. Guest name from soft context is shown to staff and not used by triage. | **F22.** Verification and triage need no PII in the model. | Send the form fields to the LLM to extract: PII leaves the system for no gain. No masking: free text carries refs and phone numbers to the model. | A surname typed into chat still reaches the LLM. See D29. |
| D4 | tech | A case has a link with a secret token, kept in a cookie. A follow-up message joins the open case for that token. | **F2.** Without login, a guest needs a way back to the case. | New case per message: splits one problem across cases. Match by cabin: joins other guests' cases. | Losing the cookie and link means starting a new case. |
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
