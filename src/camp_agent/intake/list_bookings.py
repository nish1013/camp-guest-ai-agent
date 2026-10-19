from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.guest_status import WAITING_FOR_RESTAURANT, table_line
from camp_agent.intake.answer_types import BookingLine


class ListBookings:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # The line follows the task state; only a staff confirm can make it read "Booked" (D12).
    async def __call__(self, case_id: int) -> list[BookingLine]:
        async with self._engine.connect() as conn:
            requests = await TaskRepository(conn).booking_requests(case_id)
        return [
            BookingLine(table_line(request.party, request.day, request.at), WAITING_FOR_RESTAURANT)
            for request in requests
        ]
