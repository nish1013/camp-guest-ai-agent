from pathlib import Path

import pytest

from camp_agent.config import Settings
from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_types import GuideSection
from camp_agent.guide.markdown_guide import MarkdownGuide

pytestmark = pytest.mark.anyio


def write(tmp_path: Path, text: str) -> MarkdownGuide:
    path = tmp_path / "guide.md"
    path.write_text(text, encoding="utf-8")
    return MarkdownGuide(path)


async def test_d17_demo_guide_ids() -> None:
    guide = MarkdownGuide(Settings().guide_path)

    ids = [section.id for section in await guide.search("anything")]

    assert {"emergency", "reception", "pool-hours"} <= set(ids)
    assert len(ids) == len(set(ids))


async def test_d17_section_by_id(tmp_path: Path) -> None:
    guide = write(
        tmp_path, "# Guide\n\nintro\n\n## Pool hours {#pool-hours}\n\nOpen 08:00-20:00.\n"
    )

    assert await guide.section("pool-hours") == GuideSection(
        "pool-hours", "Pool hours", "Open 08:00-20:00."
    )
    assert await guide.section("spa-hours") is None


@pytest.mark.parametrize(
    "text",
    ["## Pool hours\n\nOpen.\n", "## A {#a}\n\nx\n\n## B {#a}\n\ny\n", "## Pool {#Pool Hours}\n"],
    ids=["no-id", "repeated-id", "bad-id"],
)
async def test_d17_bad_heading_raises(tmp_path: Path, text: str) -> None:
    with pytest.raises(GuideError):
        await write(tmp_path, text).section("a")


async def test_d42_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GuideError):
        await MarkdownGuide(tmp_path / "missing.md").search("pool")
