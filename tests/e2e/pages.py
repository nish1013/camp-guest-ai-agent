import time
from datetime import date

from playwright.sync_api import Browser, BrowserContext, Locator, Page, ViewportSize
from sqlalchemy import Engine, text

from camp_agent.config import Settings
from camp_agent.qr.qr_token import QrTokens

STAY_FROM = date(2026, 10, 19)
STAY_TO = date(2026, 10, 25)
PHONE = ViewportSize(width=375, height=812)
RELOAD_S = 5.0


class GuestPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def status(self) -> Locator:
        return self.page.locator("[data-status]")

    @property
    def tickets(self) -> Locator:
        return self.page.locator("[data-ticket]")

    @property
    def bookings(self) -> Locator:
        return self.page.locator("[data-booking]")

    @property
    def reply(self) -> Locator:
        return self.page.locator("[data-reply]")

    def send(self, message: str, pick: str | None = None) -> None:
        form = self.page.locator("#message-form")
        if form.locator("[data-offer]").count():
            form.get_by_label("New request").check()
        if pick:
            form.get_by_label(pick, exact=True).check()
        form.get_by_label("How can we help?").fill(message)
        form.get_by_role("button", name="Send").click()

    def answer(self, yes: bool) -> None:
        self.page.locator("[data-question]").get_by_role(
            "button", name="Yes" if yes else "No"
        ).click()

    def step_up(self, surname: str, booking_ref: str) -> None:
        form = self.page.locator("#step-up-form")
        form.get_by_label("Booking surname").fill(surname)
        form.get_by_label("Booking reference").fill(booking_ref)
        form.get_by_role("button", name="Confirm booking").click()


class StaffPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open_case(self, case_id: int) -> None:
        self.page.goto(f"/staff/cases/{case_id}")

    def set_ticket(self, ticket_ref: str, status: str) -> None:
        form = self.page.locator(f'form[action="/staff/tickets/{ticket_ref}/status"]')
        form.get_by_label("Ticket status").select_option(status)
        form.get_by_role("button", name="Set status").click()

    def parked_reasons(self) -> Locator:
        # Staff pages do not update live, so reload until the run has parked the case.
        reasons = self.page.locator("[data-reason]")
        deadline = time.monotonic() + RELOAD_S
        self.page.goto("/staff/cases/parked")
        while not reasons.count() and time.monotonic() < deadline:
            self.page.wait_for_timeout(200)
            self.page.reload()
        return reasons

    def decide_booking(self, confirm: bool) -> None:
        self.page.locator("[data-booking-form]").get_by_role(
            "button", name="Confirm" if confirm else "Decline"
        ).click()


class Camp:
    # One running app. Each guest or staff member gets a browser context of their own, like a
    # private window, so no cookie is shared.
    def __init__(self, url: str, secret: str, browser: Browser, db: Engine) -> None:
        self.url = url
        self.db = db
        self._tokens = QrTokens(secret)
        self._browser = browser
        self._contexts: list[BrowserContext] = []

    def guest(self, cabin: str | None = None) -> GuestPage:
        page = self._page()
        if cabin:
            page.goto(f"/q/{self._tokens.issue(cabin, STAY_FROM, STAY_TO)}")
        else:
            page.goto("/")
        return GuestPage(page)

    def staff(self) -> StaffPage:
        page = self._page()
        defaults = Settings()
        page.goto("/staff/login")
        page.get_by_label("User name").fill(defaults.staff_user)
        page.get_by_label("Password").fill(defaults.staff_password.get_secret_value())
        page.get_by_role("button", name="Log in").click()
        return StaffPage(page)

    def count(self, table: str) -> int:
        with self.db.connect() as conn:
            found: int = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        return found

    def close(self) -> None:
        for context in self._contexts:
            context.close()

    def _page(self) -> Page:
        context = self._browser.new_context(base_url=self.url, viewport=PHONE)
        self._contexts.append(context)
        return context.new_page()
