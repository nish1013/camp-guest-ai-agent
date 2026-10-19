from enum import StrEnum


class QuickPick(StrEnum):
    MAINTENANCE = "maintenance"
    CLEANING = "cleaning"
    RESTAURANT = "restaurant"
    QUESTION = "question"
    RECEPTION = "reception"

    @property
    def label(self) -> str:
        return self.value.capitalize()
