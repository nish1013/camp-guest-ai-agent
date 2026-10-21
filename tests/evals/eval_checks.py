from dataclasses import dataclass

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from camp_agent.domain.arg_validation import ValidationOutcome, check_table_args, check_ticket_args
from camp_agent.domain.citation_check import AnswerOutcome, CheckedAnswer
from camp_agent.domain.routing import TaskKind, guard_route
from camp_agent.domain.table_bookings import TableBooking
from camp_agent.llm.port import Classification, TableArgs, TicketArgs
from tests.evals.eval_constants import C12, HELD_CATEGORIES, NOW, TODAY
from tests.evals.eval_types import ClassifyInput, TicketInput


@dataclass
class IntentCount(Evaluator[str, list[str], None]):
    count: int

    def evaluate(self, ctx: EvaluatorContext[str, list[str], None]) -> EvaluationReason:
        return EvaluationReason(len(ctx.output) == self.count, f"{len(ctx.output)} intents")


@dataclass
class GuardedKind(Evaluator[ClassifyInput, Classification, None]):
    kind: TaskKind

    def evaluate(
        self, ctx: EvaluatorContext[ClassifyInput, Classification, None]
    ) -> EvaluationReason:
        out = ctx.output
        decision = guard_route(out.category, out.route, C12, TODAY, HELD_CATEGORIES)
        return EvaluationReason(decision.kind is self.kind, f"{out.category}/{out.route}")


@dataclass
class TicketArgsPass(Evaluator[TicketInput, TicketArgs, None]):
    # The code validation decides, so a cross-cabin draft fails here as it is blocked in the app.
    def evaluate(self, ctx: EvaluatorContext[TicketInput, TicketArgs, None]) -> EvaluationReason:
        out = ctx.output
        check = check_ticket_args(out.tool, out.cabin, out.summary, C12.cabin)
        return EvaluationReason(check.outcome is ValidationOutcome.PASS, "; ".join(check.reasons))


@dataclass
class TableArgsPass(Evaluator[str, TableArgs, None]):
    booking: TableBooking

    def evaluate(self, ctx: EvaluatorContext[str, TableArgs, None]) -> EvaluationReason:
        out = ctx.output
        check = check_table_args(out.tool, out.cabin, out.party, out.date, out.time, C12, NOW)
        if check.outcome is not ValidationOutcome.PASS:
            return EvaluationReason(False, "; ".join(check.reasons))
        return EvaluationReason(check.booking == self.booking, f"{check.booking}")


@dataclass
class Cited(Evaluator[str, CheckedAnswer, None]):
    section_id: str

    def evaluate(self, ctx: EvaluatorContext[str, CheckedAnswer, None]) -> EvaluationReason:
        out = ctx.output
        cited = out.outcome is AnswerOutcome.CITED and out.cited == self.section_id
        return EvaluationReason(cited, f"{out.outcome}: {out.cited}")
