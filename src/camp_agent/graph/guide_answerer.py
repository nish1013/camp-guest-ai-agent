from camp_agent.domain.citation_check import CheckedAnswer, check_citation, guide_down
from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_port import GuidePort
from camp_agent.llm.llm_port import LlmPort


class GuideAnswerer:
    def __init__(self, llm: LlmPort, guide: GuidePort, reception: str) -> None:
        self._llm = llm
        self._guide = guide
        self._reception = reception

    # An LlmError propagates: the graph holds the case for a human (D16).
    async def answer(self, question: str) -> CheckedAnswer:
        try:
            sections = await self._guide.search(question)
        except GuideError:
            return guide_down(self._reception)
        if not sections:
            return check_citation("", None, frozenset(), self._reception)
        proposed = await self._llm.answer(question, sections)
        offered = {section.id for section in sections}
        return check_citation(proposed.text, proposed.section_id, offered, self._reception)
