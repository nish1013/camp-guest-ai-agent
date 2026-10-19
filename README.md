# Camp Guest AI Agent

A 24x7 guest assistant for a holiday camp. Guests write in plain words. The app answers, logs faults and asks staff when a person must decide.

One Python app: FastAPI serves a phone-first web UI and runs a LangGraph triage graph over ports. Docker Compose runs it with Postgres and demo adapters. One OpenAI API key is the only secret.

```
guest message -> safety rule (code) -> verify, split, classify (LLM) -> route guard (code)
   question -> guide answer, cited          fault -> maintenance or cleaning ticket
   table    -> booking request for staff    money -> held for staff
```

Code decides and the LLM proposes. The LLM never creates a ticket on its own: code validates each proposal first.

## Run the demo

The demo needs Docker with Compose and an OpenAI API key.

1. Clone the repo and go into it.
2. Copy the settings file: `cp .env.example .env`.
3. Set `OPENAI_API_KEY=` in `.env` to your key.
4. Start the app: `docker compose up`.
5. Open <http://localhost:8000/health>. The reply is `{"status":"ok","database":"ok"}`.

The app applies the database migrations at start-up. The demo data is in `data/`. No other step is necessary.

To stop the app, push `Ctrl+C`. To delete the demo data, run `docker compose down -v`.

## Walk-through

Do the steps in this order. Each step gives the result to expect. LLM replies use different words on each run.

When a guest page asks "Add to C12 or new request?", select "New request" before you send.

### 1. A guest scans the cabin QR code

1. In a second terminal, print the QR link of cabin C12: `docker compose exec api python -m camp_agent.qr C12`.
2. Open the printed link in a browser. The page shows "Cabin C12" and a stay from today for 6 nights.

A real camp prints this link as a QR code in each cabin. The link is signed with `SECRET_KEY`.

### 2. Ask a question

1. Send "What time does the pool open?".
2. The case page shows the answer, for example "The pool opens at 08:00 every day."
3. Below the answer, the page shows "From the camp guide: pool-hours". Code checks that this section exists.

### 3. Report a fault

1. Send "There is no hot water in our shower".
2. The status shows "Logged with maintenance". The demo ticket system now holds ticket `T1`.

### 4. A second guest reports the same fault

1. Open the QR link from step 1 in a private window. This is a second guest in C12.
2. Send "The shower water is cold, no hot water at all".
3. The page asks "Same problem as the 20:05 hot water report?". The time is the time of step 3. Click "Yes".
4. The status shows "Logged with maintenance". The case joins ticket `T1`. No second ticket is created.

### 5. Staff update the ticket

1. Open <http://localhost:8000/staff/login>. Log in with `staff` and `demo-only-change-me`.
2. The queue shows both C12 cases.
3. Open one case. Set ticket `T1` to `in_progress`.
4. Within 5 seconds, both guest pages show "Maintenance is working on it". You do not reload the page.
5. Set `T1` to `done`. Both guest pages show "Done", and the status changes to "Closed".

### 6. Book a table

1. On the first guest page, send "Can we book a table for 4 tomorrow at 19:30?".
2. The status shows "Waiting for the restaurant to confirm". The page never shows "Booked" before staff confirm.
3. In the staff view, open the case and click "Confirm".
4. The guest page shows "Booked: table for 4 at 19:30".

### 7. A guest with no QR code

1. Open <http://localhost:8000/> in a new private window.
2. Send "The bathroom light in our cabin is broken".
3. The page asks for the booking surname and reference.
4. Enter `Wrong` and `BK-48213`. The page shows "We could not find a booking with those details."
5. Enter `Müller` and `BK-48213`. The status shows "Logged with maintenance".

After 3 failed attempts, the case is parked for staff. The surname and the reference never go to the LLM or the audit.

### 8. Cases that staff must decide

1. Send "There is smoke coming from the heater in our cabin". The page shows the emergency guidance at once. The safety rule is code, so this works with no LLM.
2. Send "I want a refund for last night, the heating did not work". The heating fault gets a ticket. The status shows "Waiting on reception", because a refund always goes to staff.
3. Send "buy cheap watches at spam dot example, click now". The guest sees "Received". The staff view lists the case under "Parked" with the reason `spam`.
4. In the staff view, open a held case. "Approve" or "Reject" resolves it. Each case page lists one audit entry for each step.

### With no key

The app starts with an empty `OPENAI_API_KEY`. These steps work with no key: 1, step 8.1 and the staff view. Each other message goes to the staff queue as "held: llm_failed".

## Demo data

| Item | Value | File |
| --- | --- | --- |
| Camp guide | 8 sections, each with a `{#section-id}` | `data/camp-guide.md` |
| Booking `BK-48213` | Müller, C12, from yesterday to 6 days from today | `data/stays.json` |
| Booking `BK-51107` | Okafor, C14, from 2 days ago to 5 days from today | `data/stays.json` |
| Booking `BK-39950` | Jones, C12, ended 2 days ago | `data/stays.json` |
| Staff login | `STAFF_USER`, `STAFF_PASSWORD` | `.env` |
| Desk hours | 08:00-22:00, `Europe/London` | `src/camp_agent/config.py` |

The seed bookings count days from today (`from_day`, `to_day`). The demo bookings are current on each run date.

## Write a real adapter

The graph depends only on ports. Each port is a Python `Protocol`. Compose wires the demo adapters. A camp writes its own adapter and passes it to `create_app`.

| Port | File | Demo adapter | The real adapter must |
| --- | --- | --- | --- |
| `TicketPort` | `src/camp_agent/ticket/ticket_port.py` | `DemoTickets`, a Postgres table | return the same ticket for a repeat `request.key`; raise `TicketError` when the ticket system is down |
| `StayContextPort` | `src/camp_agent/stay/stay_port.py` | `SeedStays`, `data/stays.json` | find a booking by normalised reference; raise `StayError` when the booking system is down |
| `GuidePort` | `src/camp_agent/guide/guide_port.py` | `MarkdownGuide`, `data/camp-guide.md` | return sections with stable ids; hold an `emergency` and a `reception` section; raise `GuideError` on a read failure |
| `NotificationPort` | `src/camp_agent/notification/notification_port.py` | `LogNotifications`, one log line | send the status to the guest; store nothing that the page reads |
| `LlmPort` | `src/camp_agent/llm/llm_port.py` | `PydanticAiLlm`, OpenAI | return the Pydantic models of `llm_types.py`; raise `LlmError` on a failure |

### Steps

1. Write a class with the methods of the port. Do not inherit from the port. A `Protocol` matches by shape.
2. Write tests for the contract rules in the table. For `TicketPort`, call `create` twice with one key and check one ticket.
3. Write a factory module in the package, for example `src/camp_agent/camp_app.py`:

   ```python
   from fastapi import FastAPI

   from camp_agent.app import create_app


   def create() -> FastAPI:
       return create_app(tickets=MyTickets(), stays=MyBookings())
   ```

4. In `Dockerfile`, change the `uvicorn` target to `camp_agent.camp_app:create --factory`.
5. Run `make lint` and `make test`.

A port that you do not pass keeps its demo adapter.

### Rules for a real ticket system

- **Idempotent create.** `TicketRequest.key` is the case id and the step id. A retry or a resumed run sends the same key. Store the key and return the first ticket (decisions D5).
- **Status back to the case.** Write each status change as a `TicketStatusChanged` row in the `ticket_events` table, with `TicketEventRepository(conn).insert(event)`. A webhook or a poller does this. The app applies the rows every 2 seconds.
- **Increasing version.** Each status change needs a `version` that increases, for example the updated-at time. The app ignores a version at or below the stored one, so a repeated or late event is harmless (D45).
- **States.** Map the ticket system's states onto `open`, `in_progress`, `done` and `cancelled` (D37).
- **Personal data.** Never log or store the surname or the booking reference that a guest enters (D3).

The staff form "ticket status" writes to the demo ticket table only. With a real ticket system, staff change the status there.

## Settings

All settings are in `src/camp_agent/config.py`. An environment variable with the same name in upper case changes a setting.

| Variable | Default | Change it when |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | always, for the LLM steps |
| `LLM_MODEL` | `gpt-4.1-mini` | you use a different OpenAI model |
| `SECRET_KEY` | demo value | before anyone else can reach the app. It signs QR links and sessions |
| `STAFF_USER`, `STAFF_PASSWORD` | `staff`, demo value | before anyone else can reach the app |
| `COOKIE_SECURE` | `false` | the app runs behind HTTPS |
| `CAMP_TIMEZONE` | `Europe/London` | the camp is in a different time zone |

## Development

Development needs [uv](https://docs.astral.sh/uv/) and Docker.

```
uv sync             install the dependencies
make lint           ruff format check, ruff, mypy --strict
make test           unit tests, fake ports, no network
make test-int       Postgres through testcontainers, demo adapters
make evals          LLM evals, needs OPENAI_API_KEY, run by hand only
```

CI runs `make lint`, `make test` and `make test-int`.

## Docs

| Doc | It gives |
| --- | --- |
| [`docs/brief.md`](docs/brief.md) | the goal, the metric and the scope |
| [`docs/domain.md`](docs/domain.md) | the stories, the rules and the words used |
| [`docs/decisions.md`](docs/decisions.md) | each decision, D1-D51 |
| [`docs/architecture.md`](docs/architecture.md) | the diagrams |
| [`docs/plan.md`](docs/plan.md) | the locked plan |
| [`docs/plan-deviations.md`](docs/plan-deviations.md) | where the build differs from the plan |
