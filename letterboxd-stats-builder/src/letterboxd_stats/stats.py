"""Turn a list of films (already filtered to one period) into a stats dict.

TODO: implement `build_stats`. Planned output shape:
{
  "totals": {"logged": int, "unique": int, "rewatches": int, "avg_rating": float, "five_star": int},
  "rating_distribution": {0.5: n, ..., 5.0: n},
  "per_month": [{"month": "2026-01", "count": n}],
  "top_directors": [{"name": str, "films": [titles], "avg_rating": float | None}],
  "top_actors":    [{"name": str, "films": [titles], "avg_rating": float | None}],
  "highest_rated": [...], "lowest_rated": [...],
  "unmatched": [titles with no credits],
}
Rank people by DISTINCT films, not watch count, so rewatches do not inflate them.
"""

from __future__ import annotations

from .parse import Film


def build_stats(films: list[Film]) -> dict:
    raise NotImplementedError("build_stats is not implemented yet")
