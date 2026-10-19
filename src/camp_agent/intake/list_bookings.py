from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.guest_status import booking_status, table_line
from camp_agent.intake.answer_types import BookingLine


class ListBookings:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self, case_id: int) -> list[BookingLine]:
        async with self._engine.connect() as conn:
            requests = await TaskRepository(conn).booking_requests(case_id)
        return [
            BookingLine(
                table_line(request.booking.party, request.booking.day, request.booking.at),
                booking_status(request.state, request.booking.party, request.booking.at),
            )
            for request in requests
        ]
