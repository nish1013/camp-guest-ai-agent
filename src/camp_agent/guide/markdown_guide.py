import re
from pathlib import Path

import anyio

from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_types import GuideSection

_SECTION_START = re.compile(r"^## ", re.MULTILINE)
_HEADING = re.compile(r"(?P<title>.+?) \{#(?P<id>[a-z0-9-]+)\}")


class MarkdownGuide:
    def __init__(self, path: Path) -> None:
        self._path = anyio.Path(path)

    async def search(self, question: str) -> list[GuideSection]:
        # The demo guide is small enough to send whole; a real adapter returns the best matches.
        return list((await self._sections()).values())

    async def section(self, section_id: str) -> GuideSection | None:
        return (await self._sections()).get(section_id)

    async def _sections(self) -> dict[str, GuideSection]:
        try:
            text = await self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise GuideError(f"cannot read {self._path}") from error
        return parse_guide(text)


def parse_guide(text: str) -> dict[str, GuideSection]:
    sections: dict[str, GuideSection] = {}
    for chunk in _SECTION_START.split(text)[1:]:
        heading, _, body = chunk.partition("\n")
        match = _HEADING.fullmatch(heading.strip())
        if match is None:
            raise GuideError(f"guide heading has no section id: {heading!r}")
        if match["id"] in sections:
            raise GuideError(f"guide section id repeated: {match['id']}")
        sections[match["id"]] = GuideSection(match["id"], match["title"], body.strip())
    return sections
