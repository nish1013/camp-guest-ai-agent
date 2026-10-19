from typing import Protocol


class CaseWatch(Protocol):
    # Called after a commit that may have changed what the guest sees. Never raises.
    async def changed(self, case_id: int) -> None: ...
