# Brief review

## 2026-10-18 — review of `docs/brief.md` at `c2a37c6`

| ID | Finding | Severity | Status | Resolved by |
|---|---|---|---|---|
| F1 | Case scope has no anchor. With no login, a typed cabin number is a claim anyone can make, so the cross-cabin check protects nothing. | High | Resolved | D1, D2 |
| F2 | Case vs follow-up undefined. No rule for whether a later message joins the open case, or how a guest returns to it without login. | Medium | Resolved | D4 |
| F3 | Retries and crash between steps. A client retry, or a crash after `TicketPort` and before the case is saved, creates a second ticket. | High | Resolved | D5 |
| F4 | Two messages on one case at once. Two graph runs race on one case and overwrite each other's state. | High | Resolved | D6 |
| F5 | Duplicate reports across guests. Two guests in one cabin reporting the same fault create two tickets. | Medium | Resolved | D7 |
| F6 | "Jump the queue" names no queue. Life-safety messages depend on an LLM verdict. | High | Resolved | D8 |
| F7 | Staff view and `ResolveAsHuman` have no stated auth. Open intake would extend to approvals. | High | Resolved | D9 |
| F8 | No inbound ticket status. "Keep the guest updated until done" needs status from `TicketPort`, which only sends. | Medium | Resolved | D10 |
| F9 | Human gate has no timeout. A case can wait on an absent duty manager with no defined state. | Medium | Resolved | D11, D27 |
| F10 | Specialist action rights undefined. A restaurant booking is a side effect with no port, and "booked for 19:30" may be stated before staff confirm. | Medium | Resolved | D12 |
| F11 | Spam false positive. A genuine urgent report marked spam is dropped with no trace for staff. | High | Resolved | D13 |
| F12 | One message with two intents has no defined route. | Medium | Resolved | D14 |
| F13 | "Reject or rewrite tool calls" allows silent arg changes, against fail-closed validation. | Medium | Resolved | D15 |
| F14 | LLM unavailable, or a message that always fails, has no defined outcome. | Medium | Resolved | D16 |
| F15 | Guide answers are LLM text with no link to the guide, so invented facts are not detectable. | Low | Resolved | D17 |
| F16 | Rate limits are "if needed". Open intake makes every message an LLM cost. | Low | Resolved | D18 |
| F17 | Scope has no time bound. A guest before arrival or after departure is not covered. | Medium | Resolved | D19 |
| F18 | No rule for when a case closes or reopens. | Medium | Resolved | D20 |
| F19 | Guest language unspecified. | Low | Resolved | D21 |
| F20 | Guest update delivery unspecified for a web-only, no-login channel. | Low | Resolved | D22, D28 |
| F21 | Audit content unspecified. | Low | Resolved | D23 |
| F22 | PII reaches the LLM. Guest name is listed as triage context, and free text can hold names, phone numbers and booking refs. | High | Resolved | D3, D29 |
| F23 | Cabin hint and verified booking can disagree. Any reply that names the booking's cabin leaks booking data. | High | Resolved | D2 |
| F24 | The brief does not say which steps code decides and which the LLM proposes. | Medium | Resolved | D24, D25 |

Deferred: D26 (one-time code verification), D27 (paging), D28 (push), D29 (name detection).
