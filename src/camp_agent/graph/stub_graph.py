from camp_agent.graph.triage_graph import PendingMessage


class StubGraph:
    async def run(self, case_id: int, batch: list[PendingMessage]) -> None:
        return None
