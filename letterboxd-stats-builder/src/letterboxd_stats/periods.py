"""The five supported reporting periods.

Rolling periods end on `as_of` (default: today) and are inclusive at both ends.
The calendar year runs 1 Jan to 31 Dec of the chosen year.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

PERIODS = ("month", "3months", "6months", "year", "calendar-year")

_ROLLING_MONTHS = {"month": 1, "3months": 3, "6months": 6, "year": 12}
_LABELS = {
    "month": "Past month",
    "3months": "Past 3 months",
    "6months": "Past 6 months",
    "year": "Past year",
}


@dataclass(frozen=True)
class Period:
    id: str
    label: str
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


def _months_before(d: date, months: int) -> date:
    """Subtract whole months, clamping to the last day of a shorter month."""
    total = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def resolve_period(
    period: str,
    as_of: date | None = None,
    calendar_year: int | None = None,
) -> Period:
    as_of = as_of or date.today()

    if period == "calendar-year":
        year = calendar_year or as_of.year
        return Period(
            id=f"calendar-year-{year}",
            label=str(year),
            start=date(year, 1, 1),
            end=date(year, 12, 31),
        )

    months = _ROLLING_MONTHS.get(period)
    if months is None:
        raise ValueError(f'Unknown period "{period}". Use one of: {", ".join(PERIODS)}')

    start = _months_before(as_of, months) + timedelta(days=1)  # inclusive window
    return Period(id=period, label=_LABELS[period], start=start, end=as_of)
