"""Orquesta la generación de las dos páginas a partir de un corpus y del contenido."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

from mistsim.content.loader import Content, load_content
from mistsim.engine.game import GameResult
from mistsim.io import serial
from mistsim.report.web.cards_page import render_cards_page
from mistsim.report.web.combos import load_combos
from mistsim.report.web.images import copy_card_images
from mistsim.report.web.player_page import render_player_page

DEFAULT_MAX_GAMES = 30

PLAYER_PAGE_NAME = "partida.html"
CARDS_PAGE_NAME = "cartas.html"


@dataclass
class ReportPaths:
    player_page: Path
    cards_page: Path
    images_dir: Path
    games_shown: int
    games_truncated: bool


def _load_games(corpus_path: str | Path | None, max_games: int) -> tuple[list[GameResult], bool]:
    """Lee hasta `max_games` partidas del corpus, sin cargarlo entero en memoria.

    Sólo determina si HAY más partidas de las que se muestran, no cuántas exactamente
    — leer un corpus grande entero para contarlo sería justo el coste que se quiere
    evitar con el límite.
    """
    if corpus_path is None:
        return [], False
    reader = serial.read_corpus(corpus_path)
    peek = list(itertools.islice(reader, max_games + 1))
    truncated = len(peek) > max_games
    return peek[:max_games], truncated


def build_report(corpus_path: str | Path | None, out_dir: str | Path, *,
                 max_games: int = DEFAULT_MAX_GAMES,
                 combos_path: str | Path | None = None,
                 content: Content | None = None) -> ReportPaths:
    """Genera `partida.html` y `cartas.html` en `out_dir`.

    `corpus_path=None` (o un corpus vacío) sigue produciendo un reproductor válido,
    sólo que sin partidas que mostrar: es uno de los casos que cubren los tests.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    content = content or load_content()

    results, truncated = _load_games(corpus_path, max_games)

    images = copy_card_images([c.name for c in content.market], out_dir)
    combos = load_combos(combos_path)

    player_html = render_player_page(
        results, content, cards_page_href=CARDS_PAGE_NAME, truncated=truncated)
    cards_html = render_cards_page(
        content, images, combos, player_page_href=PLAYER_PAGE_NAME)

    player_path = out_dir / PLAYER_PAGE_NAME
    cards_path = out_dir / CARDS_PAGE_NAME
    player_path.write_text(player_html, encoding="utf-8")
    cards_path.write_text(cards_html, encoding="utf-8")

    return ReportPaths(
        player_page=player_path, cards_page=cards_path,
        images_dir=out_dir / "assets" / "images",
        games_shown=len(results), games_truncated=truncated,
    )
