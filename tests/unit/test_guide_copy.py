import pytest

from camp_agent.guide.guide_copy import copy_from_guide
from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_types import GuideSection
from tests.fakes import demo_guide, demo_section

pytestmark = pytest.mark.anyio


class OneSectionGuide:
    def __init__(self, section: GuideSection) -> None:
        self._section = section

    async def search(self, question: str) -> list[GuideSection]:
        return [self._section]

    async def section(self, section_id: str) -> GuideSection | None:
        return self._section if section_id == self._section.id else None


async def test_d42_copies_emergency_and_reception() -> None:
    copy = await copy_from_guide(demo_guide())

    assert copy.emergency == demo_section("emergency").body
    assert copy.reception == demo_section("reception").body
    assert "999" in copy.emergency
    assert "01632 960123" in copy.reception


async def test_d42_no_emergency_section_fails() -> None:
    with pytest.raises(ValueError, match="'emergency'"):
        await copy_from_guide(OneSectionGuide(demo_section("reception")))


async def test_d42_guide_down_at_start_fails() -> None:
    guide = demo_guide()
    guide.down = True

    with pytest.raises(GuideError):
        await copy_from_guide(guide)
