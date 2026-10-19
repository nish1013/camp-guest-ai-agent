from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

# First key of the two-key advisory lock: keeps ticket locks apart from cabin locks.
_TICKET_LOCK = 5


async def lock_ticket_xact(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_xact_lock(_TICKET_LOCK, func.hashtext(ticket_ref))))


async def lock_ticket(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_lock(_TICKET_LOCK, func.hashtext(ticket_ref))))


async def unlock_ticket(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_unlock(_TICKET_LOCK, func.hashtext(ticket_ref))))
