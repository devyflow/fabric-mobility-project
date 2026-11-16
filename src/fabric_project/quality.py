"""Business rules written independently of Spark for small, meaningful tests."""

from datetime import date
from decimal import Decimal


def taxi_flags(distance, fare, duration_seconds):
    flags = []
    if distance is None:
        flags.append("missing_distance")
    elif distance == 0:
        flags.append("zero_distance")
    elif distance < 0:
        flags.append("negative_distance")
    if fare is None:
        flags.append("missing_fare")
    elif fare < 0:
        flags.append("negative_fare_review")
    if duration_seconds is None:
        flags.append("missing_duration")
    elif duration_seconds < 0:
        flags.append("negative_duration")
    return flags  # Flags are observations, never an instruction to delete a row.


def usd_to_eur(amount, usd_per_eur):
    if amount is None or usd_per_eur is None:
        return None
    rate = Decimal(str(usd_per_eur))
    value = Decimal(str(amount))
    if not rate.is_finite() or rate <= 0 or not value.is_finite():
        raise ValueError("Conversion requires a finite amount and positive finite rate")
    return value / rate


def preceding_rate(day, rates, max_age_days=7):
    """rates maps ISO source dates to rates. Never look ahead or invent a rate."""
    requested = date.fromisoformat(day)
    eligible = [date.fromisoformat(d) for d in rates if date.fromisoformat(d) <= requested]
    if not eligible:
        return None
    source_day = max(eligible)
    age = (requested - source_day).days
    if age > max_age_days:
        return None
    return {"source_date": source_day.isoformat(), "age_days": age, "usd_per_eur": rates[source_day.isoformat()]}
