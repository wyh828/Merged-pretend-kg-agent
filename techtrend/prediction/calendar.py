"""Continuous calendar bins for recorded event counts; coverage remains separate."""
import pandas as pd


def calendar_bins(observed: list[str], mode: str = "month") -> list[str]:
    """Return inclusive day/month bins between observed endpoints, without I/O.

    Filling an absent bin means zero recorded events, not verified source coverage.
    Invalid dates or unsupported modes raise ValueError instead of silently sorting.
    """
    if not observed:
        return []
    if mode not in {"month", "day"}:
        raise ValueError("Calendar bin mode must be month or day")
    return pd.period_range(min(observed), max(observed), freq="M" if mode == "month" else "D").astype(str).tolist()
