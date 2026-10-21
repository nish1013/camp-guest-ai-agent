from playwright.sync_api import expect

from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, Verdict
from tests.e2e.conftest import Serve
from tests.fakes import FakeLlm

TABLE = "Can we book a table for 4 tomorrow at 19:30?"
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)
REFUND = "I want a refund for last night"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)
SMOKE = "There is smoke coming from the heater in our cabin"
SPAM = "buy cheap watches at spam dot example, click now"


def test_table_is_booked_only_after_staff_confirm(serve: Serve) -> None:
    camp = serve(FakeLlm(classes={TABLE: DINNER}))
    guest = camp.guest(cabin="C12")
    guest.send(TABLE)
    expect(guest.bookings).to_contain_text("Waiting for the restaurant to confirm")
    expect(guest.page.locator("#case")).not_to_contain_text("Booked")

    staff = camp.staff()
    staff.open_case(1)
    staff.decide_booking(confirm=True)

    expect(guest.bookings).to_contain_text("Booked: table for 4 at 19:30.")


def test_emergency_guidance_shows_with_no_llm(serve: Serve) -> None:
    camp = serve(FakeLlm(down=True))
    guest = camp.guest(cabin="C12")

    guest.send(SMOKE)

    expect(guest.page.locator("#case")).to_contain_text("call 999 now")


def test_refund_waits_on_reception(serve: Serve) -> None:
    camp = serve(FakeLlm(classes={REFUND: MONEY}))
    guest = camp.guest(cabin="C12")

    guest.send(REFUND)

    expect(guest.status).to_have_text("Waiting on reception")


def test_spam_is_parked_for_staff(serve: Serve) -> None:
    camp = serve(FakeLlm(verdicts={SPAM: Verdict.SPAM}))
    guest = camp.guest(cabin="C12")
    guest.send(SPAM)
    expect(guest.status).to_have_text("Received")

    staff = camp.staff()

    expect(staff.parked_reasons()).to_have_text("spam")
