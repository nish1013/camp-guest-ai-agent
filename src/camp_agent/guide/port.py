from dataclasses import dataclass
from typing import Protocol


class GuideError(Exception):
    pass


@dataclass(frozen=True)
class GuideSection:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class GuideCopy:
    emergency: str
    reception: str


class GuidePort(Protocol):
    # Adapters raise GuideError when the guide cannot be read.
    async def search(self, question: str) -> list[GuideSection]: ...

    async def section(self, section_id: str) -> GuideSection | None: ...


EMERGENCY_SECTION = "emergency"


RECEPTION_SECTION = "reception"


async def copy_from_guide(guide: GuidePort) -> GuideCopy:
    # Read once at start-up: an emergency reply must not wait on the guide (D8, D42).
    return GuideCopy(
        emergency=await _body(guide, EMERGENCY_SECTION),
        reception=await _body(guide, RECEPTION_SECTION),
    )


async def _body(guide: GuidePort, section_id: str) -> str:
    section = await guide.section(section_id)
    if section is None or not section.body:
        raise ValueError(f"the guide has no '{section_id}' section")
    return section.body
