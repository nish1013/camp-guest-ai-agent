from enum import StrEnum


class FaultType(StrEnum):
    HOT_WATER = "hot_water"
    HEATING = "heating"
    LEAK = "leak"
    ELECTRICS = "electrics"
    APPLIANCE = "appliance"
    CLEANING = "cleaning"
    SUPPLIES = "supplies"
    OTHER = "other"
