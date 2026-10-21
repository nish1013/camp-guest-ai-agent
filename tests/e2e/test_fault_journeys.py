from playwright.sync_api import expect

from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification
from tests.e2e.conftest import Serve
from tests.e2e.pages import Camp, GuestPage
from tests.fakes import FakeLlm

NO_HOT_WATER = "There is no hot water in our shower"
COLD_SHOWER = "The shower water is cold, no hot water at all"
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
LOGGED = "Logged with maintenance"
WORKING = "Maintenance is working on it"


def test_fault_gets_a_ticket(serve: Serve) -> None:
    camp = serve(FakeLlm(classes={NO_HOT_WATER: HOT_WATER}))
    guest = camp.guest(cabin="C12")

    guest.send(NO_HOT_WATER)

    expect(guest.tickets).to_have_text(f"{NO_HOT_WATER}: {LOGGED}")
    assert camp.count("demo_tickets") == 1


def test_second_guest_joins_the_same_ticket(serve: Serve) -> None:
    camp = serve(_shower_llm())

    _two_guests_on_one_ticket(camp)

    assert camp.count("demo_tickets") == 1


def test_staff_ticket_status_reaches_both_guests_live(serve: Serve) -> None:
    camp = serve(_shower_llm())
    guests = _two_guests_on_one_ticket(camp)
    staff = camp.staff()
    staff.open_case(1)

    staff.set_ticket("T1", "in_progress")
    for guest in guests:
        expect(guest.tickets).to_contain_text(WORKING)

    staff.set_ticket("T1", "done")
    for guest in guests:
        expect(guest.tickets).to_contain_text("Done")
        expect(guest.status).to_have_text("Closed")


def _shower_llm() -> FakeLlm:
    return FakeLlm(classes={NO_HOT_WATER: HOT_WATER, COLD_SHOWER: HOT_WATER}, same={COLD_SHOWER: 1})


def _two_guests_on_one_ticket(camp: Camp) -> tuple[GuestPage, GuestPage]:
    first = camp.guest(cabin="C12")
    first.send(NO_HOT_WATER)
    expect(first.tickets).to_have_text(f"{NO_HOT_WATER}: {LOGGED}")

    second = camp.guest(cabin="C12")
    second.send(COLD_SHOWER)
    expect(second.page.locator("[data-question]")).to_contain_text("Same problem as the")
    second.answer(yes=True)
    expect(second.tickets).to_have_text(f"{COLD_SHOWER}: {LOGGED}")
    return first, second
