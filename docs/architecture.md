# Architecture

Diagrams for [`plan.md`](plan.md). Rules and names come from [`domain.md`](domain.md).

## Ports and adapters

The graph depends only on ports. Compose wires the demo adapters; a camp wires its own.

```mermaid
flowchart LR
  subgraph Channel
    Guest["Guest web UI<br/>(HTMX, no login)"]
    Staff["Staff web UI<br/>(login, D9)"]
  end
  subgraph App["api (FastAPI)"]
    Service["Service layer<br/>SubmitMessage, ResolveAsHuman"]
    Graph["Triage graph<br/>(LangGraph)"]
    Domain["Domain<br/>Case, CabinReports"]
  end
  subgraph Ports
    GuidePort
    StayContextPort
    TicketPort
    NotificationPort
    LlmPort
  end
  subgraph Demo["Demo adapters (Compose)"]
    GuideMd["camp-guide.md"]
    SeedStays["seed stays"]
    DemoTickets["demo_tickets table"]
    CaseStatus["case status"]
    OpenAI["OpenAI via Pydantic AI"]
  end
  Guest --> Service
  Staff --> Service
  Service --> Graph
  Graph --> Domain
  Graph --> GuidePort --> GuideMd
  Graph --> StayContextPort --> SeedStays
  Graph --> TicketPort --> DemoTickets
  Graph --> NotificationPort --> CaseStatus
  Graph --> LlmPort --> OpenAI
  Service --> DB[("Postgres")]
```

## Triage graph

Code decides and the LLM proposes (D24). Every step commits one aggregate. A Case step writes one
audit entry; the report step's record is the report row (plan-deviations D11).

```mermaid
flowchart TD
  In["PII masked, message saved (D3, I1)<br/>run lease claimed (I2)"] --> Safety{"safety rule<br/>(code)"}
  Safety -- hit --> Emergency["emergency guidance<br/>hold for human"]
  Safety -- no --> Verify{"verify (LLM)"}
  Verify -- spam --> Park["park"]
  Verify -- unclear --> Clarify["clarify, max 2<br/>then hold"]
  Verify -- genuine --> Split["split intents (LLM)"]
  Split --> Classify["per task: classify (LLM)"]
  Classify --> Guard{"route guard (code)<br/>D36 list, scope?, active stay?"}
  Guard -- money --> Hold["hold for human"]
  Guard -- no scope --> StepUp["step-up form<br/>(task waits for scope)"] --> Guard
  Guard -- question --> Answer["guide answer (LLM)<br/>citation check (code)"]
  Guard -- "request, no active stay (D19)" --> Answer
  Guard -- fault --> Confirm{"2+ faults,<br/>none urgent?"}
  Confirm -- yes --> AskSplit["guest confirms split<br/>(task waits for the answer)"] --> Report
  Confirm -- no --> Report["save report<br/>(cabin lock, I4)"] --> Same{"same as an open<br/>report? (LLM)"}
  Same -- maybe --> AskSame["guest confirms<br/>(task waits for the answer)"] --> Link["link ticket"]
  Same -- different --> Args["specialist args (LLM)"]
  AskSame -- no --> Args
  Args --> Validate{"validate (code)<br/>schema, tool, scope"}
  Validate -- pass --> Ticket["TicketPort.create<br/>key: case + step"]
  Validate -- block --> Reprompt["reprompt once,<br/>then hold"]
  Guard -- table --> Booking["restaurant args (LLM)<br/>validate (code), reprompt once<br/>booking request (case lock, I8)"]
```

## Data

Two aggregates. Everything else is plain data.

```mermaid
flowchart LR
  subgraph CaseAgg["Case aggregate (lease + version)"]
    cases --> tasks
    cases --> validation_records
    cases --> verification_attempts
    cases --> audit_entries
  end
  subgraph ReportAgg["CabinReports aggregate (cabin lock)"]
    reports
  end
  subgraph Plain["Plain data"]
    messages
    ip_verification_failures
    ticket_events["ticket_events (outbox)"]
    demo_tickets
    checkpoints
  end
  messages -. case_id .-> cases
  reports -. case_id, step_id .-> tasks
  tasks -. ticket_ref .-> demo_tickets
```

## The hard part: two reports at once (I4)

```mermaid
sequenceDiagram
  participant A as Guest A (case K1)
  participant B as Guest B (case K2)
  participant DB as Postgres
  A->>DB: lock cabin C12
  B->>DB: lock cabin C12 (waits)
  A->>DB: read open reports: none
  A->>DB: insert report RA, commit (lock released)
  DB-->>B: lock granted
  B->>DB: read open reports: RA
  B->>DB: insert report RB, checked against RA, commit
  B->>B: LLM: maybe the same
  B->>B: ask guest "Same problem?"
```

## Ticket status back to the case (I12)

```mermaid
sequenceDiagram
  participant Staff
  participant Demo as Demo TicketPort
  participant Outbox as ticket_events
  participant H as ApplyTicketStatus
  participant Case as Case K1, K2
  Staff->>Demo: T7 -> in_progress
  Demo->>Outbox: same transaction: T7, in_progress, v2
  H->>Outbox: poll
  loop each task with ticket T7
    H->>Case: one transaction: set status if v2 > stored
  end
  H->>Outbox: delete handled row
```
