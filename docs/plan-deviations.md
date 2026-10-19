# Plan deviations

Where the build departs from [plan.md](plan.md), and why. A deviation becomes a decision only once it is added to [decisions.md](decisions.md).

## D1. Integration tests run in CI (PR 2, 2026-10-19)

Plan:     PR series, PR 1: "CI with ruff, mypy and unit tests". Verification lists `make test-int` as a local command.
Built:    CI also runs `make test-int`: Postgres through testcontainers on the GitHub runner's Docker.
Why:      the guards for I1, I2 and I7 are a unique key, a conditional update and a `CHECK`, all in Postgres. The unit tests use no database, so a CI run with unit tests only stays green when any of these guards is removed. Checked by removing each guard: only `tests/integration` fails.
Undo:     delete the `make test-int` step from `.github/workflows/ci.yml`.
