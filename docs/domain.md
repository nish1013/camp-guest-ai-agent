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
| open C12 maintenance ticket T7 | a second guest in C12 reports "shower is cold" | linked to T7. No new ticket. Status shows T7's state (D7). |
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
