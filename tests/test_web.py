"""Reproductor de partida y explorador de cartas: generación de HTML autocontenido.

No se editan fixtures ni tests de otros streams; `content` viene de `conftest.py` tal
cual. Todo lo demás -partidas, corpus, combos- se construye aquí.
"""
from __future__ import annotations

import json
import re

import pytest

from mistsim.cli.main import main as cli_main
from mistsim.domain.state import GameConfig
from mistsim.engine.game import GameResult
from mistsim.io import serial
from mistsim.report.web.build import build_report
from mistsim.report.web.cards_page import build_cards_data, render_cards_page
from mistsim.report.web.combos import load_combos
from mistsim.report.web.images import copy_card_images, image_filename
from mistsim.report.web.player_page import render_empty_player_page, render_player_page
from mistsim.report.web.replay import build_timeline
from mistsim.sim.batch import BatchSpec, play_one

EXTERNAL_URL = re.compile(r"https?://")


def _play(players: int = 2, turns: int = 40, seed: int = 1,
         strategies: tuple[str, ...] = ("aggro-combate", "muro-defender")) -> GameResult:
    spec = BatchSpec(strategies=strategies[:players], config=GameConfig(
        num_players=players, max_turns=turns), base_seed=seed)
    return play_one(spec, index=0, collect_log=True)


@pytest.fixture(scope="module")
def played_game():
    return _play()


@pytest.fixture(scope="module")
def zero_turn_game():
    return _play(turns=0)


# --- replay: reconstrucción de estado a partir del log ------------------------


def _flatten(timeline):
    out = []
    for block in timeline["blocks"]:
        out.extend(block["events"])
    return out


def test_timeline_events_match_the_source_log_one_to_one(played_game):
    timeline = build_timeline(played_game)
    flat = _flatten(timeline)
    original = list(played_game.log)

    assert len(flat) == len(original)
    for embedded, event in zip(flat, original, strict=True):
        assert embedded["kind"] == event.kind
        assert embedded["player"] == event.player
        assert embedded["data"] == dict(event.data)


def test_timeline_blocks_cover_every_turn_and_owner_pair_once_in_a_row(played_game):
    timeline = build_timeline(played_game)
    seen = [(b["turn"], b["owner"]) for b in timeline["blocks"]]
    # nunca dos bloques consecutivos con la misma clave (si no, no se habrían fundido)
    assert all(seen[i] != seen[i + 1] for i in range(len(seen) - 1))


def test_metal_tokens_only_take_known_states(played_game):
    timeline = build_timeline(played_game)
    for block in timeline["blocks"]:
        for player_state in block["snapshot"].values():
            assert set(player_state["metals"].values()) <= {"ready", "burned", "flared"}


def test_turn_start_resets_burned_tokens_but_not_flared():
    """Un metal quemado vuelve a listo al empezar turno; uno flareado se queda flareado
    hasta que algo lo refresque -- tal y como hace `MetalTokens` de verdad."""
    from mistsim.engine.events import Event
    from mistsim.report.web.replay import _apply

    state = {0: {"id": 0, "health": 36, "training": 0,
                "metals": {"Iron": "ready", "Steel": "ready"},
                "tracks": {}, "purchases": []}}
    _apply(Event(kind="burn", turn=1, player=0, data={"metal": "Iron"}), state, [])
    _apply(Event(kind="flare", turn=1, player=0, data={"metal": "Steel"}), state, [])
    assert state[0]["metals"] == {"Iron": "burned", "Steel": "flared"}

    turn_start_data = {"health": 36, "training": 0}
    _apply(Event(kind="turn-start", turn=2, player=0, data=turn_start_data), state, [])
    assert state[0]["metals"] == {"Iron": "ready", "Steel": "flared"}


def test_refresh_leaves_a_flared_metal_as_burned_not_ready():
    from mistsim.engine.events import Event
    from mistsim.report.web.replay import _apply
    state = {0: {"id": 0, "health": 36, "training": 0,
                "metals": {"Iron": "flared"}, "tracks": {}, "purchases": []}}
    _apply(Event(kind="refresh", turn=1, player=0, data={"metal": "Iron"}), state, [])
    assert state[0]["metals"]["Iron"] == "burned"


def test_zero_turn_game_produces_a_timeline_without_crashing(zero_turn_game):
    timeline = build_timeline(zero_turn_game)
    assert zero_turn_game.turns == 0
    assert timeline["blocks"], "hasta con 0 turnos hay al menos el bloque de arranque"
    assert timeline["blocks"][0]["owner"] is None


# --- página del reproductor ----------------------------------------------------


def test_player_page_with_no_games_is_valid_and_says_so():
    html = render_empty_player_page(reason="sin partidas")
    assert "<title>" in html
    assert "sin partidas" in html
    assert not EXTERNAL_URL.search(html)


def test_player_page_renders_for_a_real_game_without_external_refs(played_game, content):
    html = render_player_page([played_game], content)
    assert "<title>" in html
    assert not EXTERNAL_URL.search(html)
    # el aviso de datos homebrew de Misiones/Lord Ruler debe aparecer (las Misiones lo son)
    assert "homebrew" in html.lower()


def test_player_page_embedded_summary_matches_the_game_result(played_game, content):
    html = render_player_page([played_game], content)
    blob = re.search(r'id="games-data">(.*?)</script>', html, re.S).group(1)
    games = json.loads(blob)
    assert len(games) == 1
    summary = games[0]["summary"]

    assert summary["winner"] == played_game.winner
    assert summary["reason"] == played_game.reason
    assert summary["turns"] == played_game.turns
    assert summary["final_health"] == {str(k): v for k, v in played_game.final_health.items()}
    assert len(summary["players"]) == len(played_game.players)
    for embedded, original in zip(summary["players"], played_game.players, strict=True):
        assert embedded["purchases"] == original.purchases
        assert embedded["damage_dealt"] == original.damage_dealt
        assert embedded["won"] == original.won


def test_player_page_handles_multiple_games_and_a_game_selector(content):
    games = [_play(seed=s) for s in (2, 3)]
    html = render_player_page(games, content)
    assert html.count('id="games-data"') == 1
    blob = re.search(r'id="games-data">(.*?)</script>', html, re.S).group(1)
    assert len(json.loads(blob)) == 2


# --- página del explorador de cartas -------------------------------------------


def test_cards_page_lists_all_65_market_cards(content):
    images = {c.name: None for c in content.market}
    data = build_cards_data(content, images)
    assert len(data) == 65
    assert {c["name"] for c in data} == {c.name for c in content.market}


def test_cards_page_has_no_external_refs_and_is_valid(content):
    images = {c.name: None for c in content.market}
    html = render_cards_page(content, images)
    assert "<title>" in html
    assert not EXTERNAL_URL.search(html)


def test_cards_page_without_combos_shows_a_placeholder_not_a_crash(content):
    images = {c.name: None for c in content.market}
    html = render_cards_page(content, images, combos=None)
    assert "HAS_COMBOS = false" in html


def test_cards_page_with_combos_embeds_them(content):
    images = {c.name: None for c in content.market}
    combos = [{"cards": ["Dominate", "Charm"], "score": 1.8, "score_field": "lift",
              "note": None, "extra": {}}]
    html = render_cards_page(content, images, combos=combos)
    assert "HAS_COMBOS = true" in html
    blob = re.search(r'id="combos-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(blob)[0]["cards"] == ["Dominate", "Charm"]


# --- imágenes de carta -----------------------------------------------------------


def test_image_filename_has_two_documented_typo_overrides():
    assert image_filename("Crushing Blow") == "cushingblow.png"
    assert image_filename("Maelstrom") == "maelstorm.png"
    assert image_filename("Dominate") == "dominate.png"
    assert image_filename("Crew Leader") == "crewleader.png"


def test_copy_card_images_resolves_all_65_and_skips_missing(tmp_path, content):
    names = [c.name for c in content.market] + ["Carta Que No Existe"]
    mapping = copy_card_images(names, tmp_path)
    assert mapping["Carta Que No Existe"] is None
    resolved = [p for p in mapping.values() if p is not None]
    assert len(resolved) == 65
    for rel in resolved:
        assert (tmp_path / rel).exists()


# --- hueco de combos: tolerante a que el fichero no exista o esté mal formado ---


def test_load_combos_missing_file_returns_none(tmp_path):
    assert load_combos(tmp_path / "no-existe.json") is None


def test_load_combos_none_path_returns_none():
    assert load_combos(None) is None


def test_load_combos_malformed_json_returns_none_not_raise(tmp_path):
    path = tmp_path / "combos.json"
    path.write_text("{esto no es json", encoding="utf-8")
    assert load_combos(path) is None


def test_load_combos_wrong_shape_returns_none(tmp_path):
    path = tmp_path / "combos.json"
    path.write_text(json.dumps({"algo": "distinto"}), encoding="utf-8")
    assert load_combos(path) is None


def test_load_combos_valid_file_is_sorted_by_score(tmp_path):
    path = tmp_path / "combos.json"
    path.write_text(json.dumps({"combos": [
        {"cards": ["A", "B"], "lift": 1.2},
        {"cards": ["C", "D"], "lift": 3.4},
        {"cards": ["sin-numero"]},  # menos de 2 cartas -> descartada
        {"cards": ["E", "F"]},      # sin score reconocido -> se queda al final
    ]}), encoding="utf-8")
    combos = load_combos(path)
    assert [c["cards"] for c in combos] == [["C", "D"], ["A", "B"], ["E", "F"]]


# --- orquestador end-to-end -------------------------------------------------------


def test_build_report_with_no_corpus_does_not_crash(tmp_path):
    paths = build_report(None, tmp_path)
    assert paths.games_shown == 0
    assert paths.player_page.exists()
    assert paths.cards_page.exists()
    assert "sin partidas" in paths.player_page.read_text(encoding="utf-8").lower() \
        or "no traía" in paths.player_page.read_text(encoding="utf-8")


def test_build_report_with_empty_corpus_file_does_not_crash(tmp_path):
    empty = tmp_path / "vacio.jsonl"
    empty.write_text("", encoding="utf-8")
    paths = build_report(empty, tmp_path / "out")
    assert paths.games_shown == 0
    assert paths.player_page.exists()


def test_build_report_writes_both_pages_and_copies_images(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    serial.write_corpus(corpus, [_play(seed=9)], include_log=True)
    out = tmp_path / "informe"
    paths = build_report(corpus, out)

    assert paths.games_shown == 1
    assert not paths.games_truncated
    assert paths.player_page.read_text(encoding="utf-8")
    assert paths.cards_page.read_text(encoding="utf-8")
    assert any(paths.images_dir.glob("*.png"))


def test_build_report_respects_max_games_and_flags_truncation(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    games = [_play(seed=s) for s in range(4)]
    serial.write_corpus(corpus, games, include_log=True)

    paths = build_report(corpus, tmp_path / "out", max_games=2)
    assert paths.games_shown == 2
    assert paths.games_truncated
    assert "hay más" in paths.player_page.read_text(encoding="utf-8")


def test_cli_report_command_runs_end_to_end(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    serial.write_corpus(corpus, [_play(seed=5)], include_log=True)
    out = tmp_path / "informe"

    rc = cli_main(["report", "--corpus", str(corpus), "--out", str(out)])

    assert rc == 0
    assert (out / "partida.html").exists()
    assert (out / "cartas.html").exists()
