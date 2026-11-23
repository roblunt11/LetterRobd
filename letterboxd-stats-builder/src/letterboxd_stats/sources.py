"""Choose and build the credits source."""

from __future__ import annotations

from typing import Callable

from . import PROJECT_URL, __version__
from .config import SOURCES, Config
from .enrich import SourceError
from .tmdb import TmdbClient
from .wikidata import WikidataClient


def user_agent(contact: str | None) -> str:
    """Wikimedia's policy wants the app name, version and a way to contact the operator."""
    return f"letterboxd-stats-builder/{__version__} ({contact or PROJECT_URL})"


def make_client_factory(config: Config) -> Callable[[], object]:
    """A zero-argument factory, so a fully cached run never builds a client (or needs a key)."""
    if config.source == "tmdb":
        return lambda: TmdbClient(config.tmdb_api_key)
    return lambda: WikidataClient(user_agent(config.contact))


def check_source(client) -> str:
    """One real lookup so the user can confirm the source works. Returns a summary line."""
    result = client.lookup("Fight Club", 1999)
    if result is None:
        raise SourceError(f"The {client.name} source answered but the test lookup found nothing.")
    director = ", ".join(result["directors"]) or "no director listed"
    return f'{client.name} source OK: found "{result["title"]}", directed by {director}.'
