"""Fill templates/page.html with a stats dict and write it to the output folder.

TODO: implement `render_page`. Planned output:
  dist/index.html          period switcher / landing page
  dist/<period-id>.html    one page per period (month, 3months, 6months, year, calendar-year-YYYY)
Keep pages self-contained (inline CSS/JS, no external requests) so they work on
GitHub Pages or straight from disk. Load the template with importlib.resources.
"""

from __future__ import annotations

from pathlib import Path

from .periods import Period


def render_page(period: Period, stats: dict, out_dir: Path) -> Path:
    raise NotImplementedError("render_page is not implemented yet")
