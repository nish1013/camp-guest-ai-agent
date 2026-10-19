from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel


class HealthProbe(Protocol):
    async def is_up(self) -> bool: ...


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


router = APIRouter()


def get_probe(request: Request) -> HealthProbe:
    probe: HealthProbe = request.app.state.health_probe
    return probe


@router.get("/health")
async def health(
    response: Response, probe: Annotated[HealthProbe, Depends(get_probe)]
) -> HealthResponse:
    if await probe.is_up():
        return HealthResponse(status="ok", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", database="unavailable")
