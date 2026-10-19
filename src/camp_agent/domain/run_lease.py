from datetime import datetime


def run_active(lease_until: datetime | None, now: datetime) -> bool:
    # The same test as the claim: a lease at or before now is free (I2).
    return lease_until is not None and lease_until > now
