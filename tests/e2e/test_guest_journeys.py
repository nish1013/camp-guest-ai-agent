from playwright.sync_api import Page, expect

from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, GuideAnswer
from tests.e2e.conftest import Serve
from tests.fakes import FakeLlm

POOL = "What time does the pool open?"
POOL_ANSWER = "The pool is open 08:00-20:00 every day."
REFUND = "I want a refund for last night, the heating did not work"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)
LIGHT = "The bathroom light in our cabin is broken"
ELECTRICS = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.NORMAL,
    fault_type=FaultType.ELECTRICS,
)


def test_question_answer_cites_the_guide(serve: Serve) -> None:
    camp = serve(FakeLlm(answers={POOL: GuideAnswer(text=POOL_ANSWER, section_id="pool-hours")}))
    guest = camp.guest(cabin="C12")

    guest.send(POOL)

    answer = guest.page.locator("[data-answer]")
    expect(answer).to_contain_text(POOL_ANSWER)
    expect(answer.locator("[data-cited]")).to_have_text("pool-hours")


def test_guest_without_qr_confirms_the_booking(serve: Serve) -> None:
    camp = serve(FakeLlm(classes={LIGHT: ELECTRICS}))
    guest = camp.guest()
    guest.send(LIGHT)

    guest.step_up("Wrong", "BK-48213")
    expect(guest.reply).to_have_text("We could not find a booking with those details.")

    guest.step_up("Müller", "BK-48213")
    expect(guest.tickets).to_have_text(f"{LIGHT}: Logged with maintenance")


def test_pages_fit_a_phone_screen(serve: Serve) -> None:
    camp = serve(FakeLlm(classes={REFUND: MONEY}))
    guest = camp.guest(cabin="C12")
    guest.send(REFUND)
    expect(guest.status).to_have_text("Waiting on reception")
    staff = camp.staff()
    expect(staff.page.locator("[data-case]")).to_have_count(1)

    for page in (guest.page, staff.page):
        assert _scroll_overflow(page) == 0, page.url


def _scroll_overflow(page: Page) -> int:
    overflow: int = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    return overflow
