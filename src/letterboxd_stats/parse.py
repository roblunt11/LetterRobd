"""Read the Letterboxd export.

TODO: implement `parse_diary`.
  - Accept either the .zip or an already-extracted folder (zipfile + csv, stdlib only).
  - Read diary.csv. Columns: Date, Name, Year, Letterboxd URI, Rating, Rewatch, Tags, Watched Date
  - Use "Watched Date" for period filtering, NOT "Date" (that is the day it was logged).
  - Rating can be empty (unrated). Rewatch is "Yes" or empty. Tags is comma-separated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Film:
    name: str
    year: int
    watched: date
    rating: float | None = None
    rewatch: bool = False
    uri: str = ""
    tags: list[str] = field(default_factory=list)
    # Filled in by enrich.py
    tmdb_id: int | None = None
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)


def parse_diary(input_path: Path) -> list[Film]:
    raise NotImplementedError("parse_diary is not implemented yet")
