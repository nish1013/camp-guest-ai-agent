from camp_agent.guide.guide_port import GuidePort
from camp_agent.guide.guide_types import GuideCopy

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
