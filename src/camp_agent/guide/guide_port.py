from typing import Protocol

from camp_agent.guide.guide_types import GuideSection


class GuidePort(Protocol):
    # Adapters raise GuideError when the guide cannot be read.
    async def search(self, question: str) -> list[GuideSection]: ...

    async def section(self, section_id: str) -> GuideSection | None: ...
