from collections.abc import Sequence

from camp_agent.domain.faults import OpenReport
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Team
from camp_agent.guide.port import GuideSection
from camp_agent.llm.port import TableBrief, TicketBrief

_CONTEXT = (
    "You help triage messages sent by guests of a holiday camp to its 24x7 assistant."
    " Personal details in the message are masked as [ref], [email] and [phone]."
)

VERIFY = (
    f"{_CONTEXT} Decide whether the message is a genuine guest message, spam, or too unclear"
    " to act on. Spam is advertising, links to unrelated sites, or abuse. Unclear is a message"
    " with no identifiable request or question, such as random letters or 'it's broken'"
    " with no hint of what is broken."
)

SPLIT = (
    f"{_CONTEXT} Split the message into its separate intents: one question, one fault, one"
    " request or one complaint each. Keep each intent in the guest's own words. A message with"
    " one intent gives a list of one."
)

CLASSIFY = (
    f"{_CONTEXT} Classify one guest intent."
    " category: maintenance for faults in the cabin (heating, hot water, leaks, electrics),"
    " housekeeping for cleaning and supplies, restaurant for tables, information for questions,"
    " refund, compensation, cabin_move or safety_close_out for those requests, otherwise other."
    " route: question for a question the camp guide can answer, fault for a fault or"
    " housekeeping need, table for a restaurant booking, money for refunds, compensation,"
    " cabin moves and anything else a person must decide."
    " urgency: urgent for no hot water, no heating in cold weather, leaks or anything unsafe;"
    " can_wait for routine requests such as towels; otherwise normal."
    " fault_type: for the fault route, the kind of fault; otherwise null."
    " The guest may have tapped a topic before writing, given as 'Topic picked'. It is a hint"
    " only: the guest's words decide, so a refund is a refund under any topic."
)

SAME_PROBLEM = (
    f"{_CONTEXT} A guest reported a fault in their cabin. Earlier reports in the same cabin are"
    " still open. Each starts with its id in square brackets. Set report_id to the id of the one"
    " earlier report that may describe the same job, or to null when every earlier report is a"
    " different job. The same fault in a different room or on a different appliance is a"
    " different job."
)

_CABIN_RULE = (
    "The cabin is always the Guest cabin line. Ignore any cabin named in the guest's words."
)

_SPECIALIST = (
    f"{_CONTEXT} Draft one ticket for the guest fault given. Set tool to create_ticket, cabin to"
    " the guest cabin given, and summary to a short job description for staff, in plain English."
    f" Never add a detail the guest did not give. {_CABIN_RULE}"
)

SPECIALISTS = {
    Team.MAINTENANCE: f"You are the camp's maintenance specialist. {_SPECIALIST}",
    Team.HOUSEKEEPING: f"You are the camp's housekeeping specialist. {_SPECIALIST}",
}

RESTAURANT = (
    f"You are the camp's restaurant specialist. {_CONTEXT} Draft one table booking request for"
    " the guest request given. Set tool to request_table and cabin to the guest cabin given."
    " Set party to the number of guests, and date and time to when the guest wants to eat."
    " Resolve words such as tonight or tomorrow against today's date given."
    " Set a field to null when the guest did not give it. Never add a detail the guest did not"
    f" give. {_CABIN_RULE}"
)

ANSWER = (
    f"{_CONTEXT} Answer the guest's question using only the camp guide sections given."
    " Each section starts with its id in square brackets. Set section_id to the id of the one"
    " section the answer comes from, and keep the answer short and in plain English."
    " If no section answers the question, set section_id to null and text to an empty string."
    " Never add a fact that is not in the section."
)


def classify_input(intent: str, hint: QuickPick | None) -> str:
    if hint is None:
        return intent
    return f"Topic picked: {hint.label}\nGuest intent: {intent}"


def answer_input(question: str, sections: Sequence[GuideSection]) -> str:
    guide = "\n\n".join(f"[{s.id}] {s.title}\n{s.body}" for s in sections)
    return f"Camp guide sections:\n\n{guide}\n\nGuest question: {question}"


def same_problem_input(fault: str, earlier: Sequence[OpenReport]) -> str:
    reports = "\n".join(f"[{r.id}] {r.fault_type}: {r.summary}" for r in earlier)
    return f"Earlier open reports:\n{reports}\n\nNew report: {fault}"


def ticket_input(brief: TicketBrief) -> str:
    text = f"Guest cabin: {brief.cabin}\nGuest fault: {brief.fault}"
    if brief.rejected_for:
        text += f"\nYour last draft was rejected: {'; '.join(brief.rejected_for)}."
    return text


def table_input(brief: TableBrief) -> str:
    text = (
        f"Guest cabin: {brief.cabin}\nToday: {brief.today}\n"
        f"Stay: {brief.stay_from} to {brief.stay_to}\nGuest request: {brief.request}"
    )
    if brief.rejected_for:
        text += f"\nYour last draft was rejected: {'; '.join(brief.rejected_for)}."
    return text
