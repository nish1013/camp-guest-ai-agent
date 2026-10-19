from dataclasses import dataclass


@dataclass(frozen=True)
class GuideSection:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class GuideCopy:
    emergency: str
    reception: str
