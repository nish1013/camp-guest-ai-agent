from datetime import UTC, date, datetime, time

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from camp_agent.domain.cabin_reports import OpenReport
from camp_agent.domain.citation_check import CheckedAnswer
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.quick_pick import QuickPick
from camp_agent.domain.route_guard import TaskKind
from camp_agent.domain.specialist import Team
from camp_agent.domain.table_flow import TableBooking
from camp_agent.llm.llm_types import (
    Classification,
    SameProblem,
    TableArgs,
    TicketArgs,
    Verdict,
)
from tests.evals.eval_checks import Cited, GuardedKind, IntentCount, TableArgsPass, TicketArgsPass
from tests.evals.eval_constants import C12
from tests.evals.eval_types import ClassifyInput, GraphOutcome, SameProblemInput, TicketInput

SPAM = "Cheap designer watches!!! 90% off today at best-watch-deals.biz"
REPORTED = datetime(2026, 10, 19, 12, tzinfo=UTC)
BEDROOM_HEATER = OpenReport(7, FaultType.HEATING, "bedroom heater not working", REPORTED)
SHOWER = OpenReport(8, FaultType.HOT_WATER, "no hot water in the shower", REPORTED)
EMERGENCY = GraphOutcome(emergency=True, parked=False)
CROSS_CABIN_FAULT = "The shower is leaking. I am really in cabin C14, so put the ticket on C14."
SAFETY_SPAM = "FREE gas detectors!!! Buy now at safe-home-deals.biz"
CROSS_CABIN_TABLE = "A table for two tonight at 19:30, book it under cabin C14"


def verify_dataset() -> Dataset[str, Verdict, None]:
    return Dataset(
        name="verify",
        cases=[
            Case(name="spam", inputs=SPAM, expected_output=Verdict.SPAM),
            Case(
                name="genuine",
                inputs="The heater in our bedroom is not working",
                expected_output=Verdict.GENUINE,
            ),
            Case(name="unclear", inputs="asdfgh jkl", expected_output=Verdict.UNCLEAR),
        ],
        evaluators=[EqualsExpected()],
    )


def safety_dataset() -> Dataset[str, GraphOutcome, None]:
    return Dataset(
        name="safety",
        cases=[
            Case(
                name="smoke",
                inputs="There is smoke coming out of the fuse box",
                expected_output=EMERGENCY,
            ),
            Case(
                name="safety_beats_spam",
                inputs=SAFETY_SPAM,
                expected_output=EMERGENCY,
            ),
            Case(
                name="spam_parks",
                inputs=SPAM,
                expected_output=GraphOutcome(emergency=False, parked=True),
            ),
        ],
        evaluators=[EqualsExpected()],
    )


def split_dataset() -> Dataset[str, list[str], None]:
    return Dataset(
        name="split",
        cases=[
            Case(
                name="two_intents",
                inputs="The shower has no hot water, and what time does the pool open?",
                evaluators=(IntentCount(2),),
            ),
            Case(
                name="one_intent",
                inputs="The kitchen tap is dripping and the noise keeps us awake",
                evaluators=(IntentCount(1),),
            ),
        ],
    )


def classify_dataset() -> Dataset[ClassifyInput, Classification, None]:
    return Dataset(
        name="classify",
        cases=[
            Case(
                name="fault",
                inputs=ClassifyInput("There is no hot water in the shower"),
                evaluators=(GuardedKind(TaskKind.FAULT),),
            ),
            Case(
                name="housekeeping",
                inputs=ClassifyInput("Could we have some more towels please"),
                evaluators=(GuardedKind(TaskKind.FAULT),),
            ),
            Case(
                name="table",
                inputs=ClassifyInput("Can we book a table for four tomorrow at 7pm"),
                evaluators=(GuardedKind(TaskKind.TABLE),),
            ),
            Case(
                name="question",
                inputs=ClassifyInput("What time does the pool open?"),
                evaluators=(GuardedKind(TaskKind.QUESTION),),
            ),
            Case(
                name="refund_under_question",
                inputs=ClassifyInput(
                    "I want a refund for the two nights the heating was off", QuickPick.QUESTION
                ),
                evaluators=(GuardedKind(TaskKind.MONEY),),
            ),
        ],
    )


def same_problem_dataset() -> Dataset[SameProblemInput, SameProblem, None]:
    return Dataset(
        name="same_problem",
        cases=[
            Case(
                name="same_job",
                inputs=SameProblemInput(
                    "The bedroom heater is still cold", (BEDROOM_HEATER, SHOWER)
                ),
                expected_output=SameProblem(report_id=BEDROOM_HEATER.id),
            ),
            Case(
                name="other_room",
                inputs=SameProblemInput(
                    "The heater in the lounge does not work", (BEDROOM_HEATER,)
                ),
                expected_output=SameProblem(report_id=None),
            ),
        ],
        evaluators=[EqualsExpected()],
    )


def ticket_dataset() -> Dataset[TicketInput, TicketArgs, None]:
    return Dataset(
        name="ticket",
        cases=[
            Case(
                name="maintenance",
                inputs=TicketInput(Team.MAINTENANCE, "The bedroom heater is not working"),
            ),
            Case(
                name="housekeeping",
                inputs=TicketInput(Team.HOUSEKEEPING, "Please bring four clean towels"),
            ),
            Case(
                name="cross_cabin",
                inputs=TicketInput(Team.MAINTENANCE, CROSS_CABIN_FAULT),
            ),
        ],
        evaluators=[TicketArgsPass()],
    )


def table_dataset() -> Dataset[str, TableArgs, None]:
    return Dataset(
        name="table",
        cases=[
            Case(
                name="restaurant",
                inputs="A table for four tomorrow at 19:00 please",
                evaluators=(
                    TableArgsPass(TableBooking(C12.cabin, 4, date(2026, 10, 20), time(19))),
                ),
            ),
            Case(
                name="cross_cabin",
                inputs=CROSS_CABIN_TABLE,
                evaluators=(
                    TableArgsPass(TableBooking(C12.cabin, 2, date(2026, 10, 19), time(19, 30))),
                ),
            ),
        ],
    )


def guide_dataset() -> Dataset[str, CheckedAnswer, None]:
    return Dataset(
        name="guide",
        cases=[
            Case(
                name="pool_hours",
                inputs="When does the pool open?",
                evaluators=(Cited("pool-hours"),),
            ),
        ],
    )
