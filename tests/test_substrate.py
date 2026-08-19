"""Sustrato compartido de la Fase A.

Estos contratos los consumen los cuatro streams de la 2ª entrega (optimizador, minería
de combos, solver y visor web). Romperlos rompe a los cuatro a la vez, así que se
prueban aquí con más celo del habitual.
"""
import copy
import random

import pytest

from mistsim.agents import archetypes
from mistsim.domain.state import GameConfig, Mode
from mistsim.engine.events import EventLog
from mistsim.engine.game import GameEngine
from mistsim.engine.setup import new_game
from mistsim.io import serial


@pytest.fixture
def state(content):
    return new_game(content, GameConfig(num_players=4),
                    ["vin", "kelsier", "shan", "marsh"], random.Random(1), EventLog())


# --- A4: clonado de estado ---------------------------------------------------


def test_clone_is_fully_isolated(state):
    clone = state.clone()
    clone.players[0].health = 1
    clone.players[0].hand.clear()
    clone.market.row.pop()
    clone.tracks[0].positions[0] = 9
    clone.eliminated.append(clone.players[1].deck.pop())

    assert state.players[0].health != 1
    assert state.players[0].hand
    assert len(state.market.row) == 6
    assert state.tracks[0].position_of(0) == 0
    assert state.eliminated == []


def test_clone_shares_immutable_content_but_not_instances(state):
    """Las definiciones se comparten (por velocidad); las instancias, nunca."""
    clone = state.clone()
    assert clone.market.row[0].card is state.market.row[0].card
    assert clone.tracks[0].mission is state.tracks[0].mission
    assert clone.players[0].character is state.players[0].character

    assert clone.market.row[0] is not state.market.row[0]
    assert clone.players[0].tokens is not state.players[0].tokens
    assert clone.players[0].resources is not state.players[0].resources


def test_clone_copies_the_rng_so_branches_are_comparable(state):
    """Si el azar divergiera entre ramas, el solver compararía peras con manzanas."""
    clone = state.clone()
    assert [clone.rng.random() for _ in range(5)] == [state.rng.random() for _ in range(5)]


def test_clone_matches_deepcopy_field_by_field(state):
    """Red de seguridad: `clone` está escrito a mano por velocidad (~29x).

    Si alguien añade un campo mutable a GameState, Player, Market o MissionTrack y no lo
    refleja en `clone`, este test lo caza comparando contra la copia profunda genérica.
    """
    # Estado con juego avanzado, para que los campos no estén todos vacíos.
    player = state.players[0]
    player.resources.coin = 3
    player.used_once_per_turn.add("character")
    player.permanents["coin"] = 2
    player.in_play.append(player.hand.pop())
    player.allies.append(player.hand.pop())
    state.tracks[0].positions[0] = 4
    state.tracks[0].claimed.add((0, 2))
    state.tracks[0].first_claimed.add(2)
    state.eliminated.append(player.deck.pop())

    manual, generic = state.clone(), copy.deepcopy(state)

    def snapshot(st):
        return {
            "turn": st.turn, "active": st.active, "winner": st.winner,
            "reason": st.victory_reason, "finished": st.finished,
            "target": st.target_holder,
            "market": ([c.uid for c in st.market.row], [c.uid for c in st.market.deck]),
            "eliminated": [c.uid for c in st.eliminated],
            "tracks": [(t.mission.name, dict(t.positions), sorted(t.claimed),
                        sorted(t.first_claimed), t.finisher)
                       for t in st.tracks],
            "players": [
                (p.id, p.health, p.boxings, p.atium, p.training, p.eliminated,
                 [c.uid for c in p.deck], [c.uid for c in p.hand],
                 [c.uid for c in p.discard], [c.uid for c in p.in_play],
                 [c.uid for c in p.allies], [c.uid for c in p.set_aside],
                 dict(p.tokens.state), p.tokens.burn_limit, p.tokens.burns_used,
                 p.resources.coin, p.resources.combat, p.resources.mission,
                 sorted(p.used_once_per_turn), dict(p.metal_burn_counts),
                 dict(p.permanents))
                for p in st.players
            ],
        }

    assert snapshot(manual) == snapshot(generic)


def test_clone_handles_coop_state(content):
    state = new_game(content, GameConfig(mode=Mode.COOP, num_players=2),
                     ["vin", "kelsier"], random.Random(2), EventLog())
    state.lord_ruler.shields["adv_00"] = ["X", 3]
    state.lord_ruler.assigned_to["adv_00"] = 1

    clone = state.clone()
    clone.lord_ruler.health = 1
    clone.lord_ruler.shields["adv_00"].pop()

    assert state.lord_ruler.health == 48
    assert state.lord_ruler.shields["adv_00"] == ["X", 3]


# --- A1: datos por jugador ---------------------------------------------------


def test_player_results_are_derived_for_every_seat(content):
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=3, max_turns=25), seed=5)
    result = engine.run([_agent("aggro-combate"), _agent("rush-mision"),
                         _agent("motor-riot")])

    assert len(result.players) == 3
    for seat, pr in enumerate(result.players):
        assert pr.player_id == seat
        assert pr.rank in (1, 2, 3)
        assert pr.damage_dealt >= 0 and pr.damage_taken >= 0
    assert {p.rank for p in result.players} == {1, 2, 3}
    assert [p.strategy for p in result.players] == [
        "aggro-combate", "rush-mision", "motor-riot"]


def test_damage_dealt_and_taken_balance_out(content):
    """Todo daño que alguien reparte lo recibe alguien: cuadra la contabilidad."""
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=2, max_turns=30), seed=8)
    result = engine.run([_agent("aggro-combate"), _agent("aggro-combate")])
    assert (sum(p.damage_dealt for p in result.players)
            == sum(p.damage_taken for p in result.players))


def test_the_winner_ranks_first(content):
    for seed in range(6):
        engine = GameEngine(content=content,
                            config=GameConfig(num_players=2, max_turns=30), seed=seed)
        result = engine.run([_agent("rush-mision"), _agent("rampa-economica")])
        if result.winner is not None:
            assert result.players[result.winner].rank == 1
            assert result.players[result.winner].won is True


def test_coop_marks_the_whole_team_as_winners(content):
    """En Solo/Coop se gana o se pierde en equipo, no por asiento."""
    for seed in range(25):
        engine = GameEngine(content=content,
                            config=GameConfig(mode=Mode.COOP, num_players=2,
                                              max_turns=40),
                            seed=seed)
        result = engine.run([_agent("aggro-combate"), _agent("aggro-combate")])
        if result.players_won:
            assert all(p.won for p in result.players)
            return
    pytest.skip("no se ganó ninguna partida coop en las semillas probadas")


# --- A2: serialización -------------------------------------------------------


def test_result_survives_a_roundtrip(content):
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=2, max_turns=20), seed=3)
    result = engine.run([_agent("adelgazar"), _agent("tempo-seek")])

    back = serial.result_from_dict(serial.result_to_dict(result))
    assert (back.winner, back.reason, back.turns) == (
        result.winner, result.reason, result.turns)
    assert back.final_health == result.final_health
    assert back.mission_positions == result.mission_positions
    assert len(back.log) == len(result.log)
    assert [serial.player_to_dict(p) for p in back.players] == [
        serial.player_to_dict(p) for p in result.players]


def test_result_can_be_serialised_without_the_log(content):
    """El log es lo más pesado; un corpus de análisis no lo necesita."""
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=2, max_turns=20), seed=3)
    result = engine.run([_agent("motor-robo"), _agent("muro-defender")])

    slim = serial.result_to_dict(result, include_log=False)
    assert "log" not in slim
    assert slim["players"], "los datos por jugador deben sobrevivir"
    assert len(serial.result_from_dict(slim).log) == 0


@pytest.mark.parametrize("name", archetypes.names())
def test_every_archetype_survives_a_roundtrip(name):
    """Los perfiles usan enums Metal y Tag como claves; JSON sólo admite cadenas."""
    original = archetypes.get(name)
    back = serial.profile_from_dict(serial.profile_to_dict(original))
    assert back.name == original.name
    assert back.weights == original.weights
    assert back.metal_affinity == original.metal_affinity
    assert back.tag_affinity == original.tag_affinity
    assert back.mission_focus == original.mission_focus


def test_corpus_roundtrips_through_jsonl(content, tmp_path):
    results = [
        GameEngine(content=content,
                   config=GameConfig(num_players=2, max_turns=15), seed=s).run(
            [_agent("equilibrado"), _agent("aggro-combate")])
        for s in range(4)
    ]
    path = tmp_path / "corpus.jsonl"
    assert serial.write_corpus(path, results) == 4

    back = list(serial.read_corpus(path))
    assert len(back) == 4
    assert [r.reason for r in back] == [r.reason for r in results]
    assert [len(r.players) for r in back] == [2] * 4

    raw = list(serial.read_corpus_dicts(path))
    assert [d["reason"] for d in raw] == [r.reason for r in results]


def test_corpus_appends_without_rewriting(content, tmp_path):
    path = tmp_path / "corpus.jsonl"
    for seed in range(3):
        result = GameEngine(content=content,
                            config=GameConfig(num_players=2, max_turns=12),
                            seed=seed).run([_agent("equilibrado")] * 2)
        serial.write_corpus(path, [result], append=seed > 0)
    assert len(list(serial.read_corpus(path))) == 3


def _agent(name):
    from mistsim.agents.utility import make
    return make(name, 1)


# --- A3: runner de lotes -----------------------------------------------------


def _spec(**kwargs):
    from mistsim.sim.batch import BatchSpec
    base = {
        "strategies": ("aggro-combate", "rush-mision"),
        "config": GameConfig(num_players=2, max_turns=20),
        "base_seed": 500,
    }
    base.update(kwargs)
    return BatchSpec(**base)


def test_batch_is_deterministic_regardless_of_worker_count():
    """El contrato que hace reproducible todo el análisis posterior.

    Las semillas se derivan del índice de partida, no de un RNG compartido, y el pool
    devuelve en orden. Si esto se rompe, dos ejecuciones del mismo lote dan números
    distintos y ningún resultado del optimizador es comparable con el anterior.
    """
    from mistsim.sim.batch import run_batch

    spec = _spec()
    serial_run = [(r.reason, r.turns, r.winner)
                  for r in run_batch(spec, 12, workers=1, collect_log=False)]
    parallel = [(r.reason, r.turns, r.winner)
                for r in run_batch(spec, 12, workers=4, collect_log=False)]
    assert serial_run == parallel


def test_batch_reruns_identically(content):
    from mistsim.sim.batch import run_batch

    spec = _spec()
    first = [r.turns for r in run_batch(spec, 8, workers=1, collect_log=False)]
    second = [r.turns for r in run_batch(spec, 8, workers=1, collect_log=False)]
    assert first == second


def test_different_base_seeds_give_different_games():
    from mistsim.sim.batch import run_batch

    a = [r.turns for r in run_batch(_spec(base_seed=1), 10, workers=1, collect_log=False)]
    b = [r.turns for r in run_batch(_spec(base_seed=999), 10, workers=1, collect_log=False)]
    assert a != b


def test_player_metrics_survive_a_quiet_batch():
    """`collect_log=False` filtra el log pero debe conservar las métricas por jugador."""
    from mistsim.sim.batch import run_batch

    spec = _spec()
    loud = list(run_batch(spec, 4, workers=1, collect_log=True))
    quiet = list(run_batch(spec, 4, workers=1, collect_log=False))

    for a, b in zip(loud, quiet, strict=True):
        assert [p.purchases for p in a.players] == [p.purchases for p in b.players]
        assert [p.damage_dealt for p in a.players] == [p.damage_dealt for p in b.players]
        assert [p.mission_points_spent for p in a.players] == [
            p.mission_points_spent for p in b.players]
    assert len(quiet[0].log) < len(loud[0].log), "el log filtrado debe ser más pequeño"


def test_batch_accepts_custom_profiles_not_in_the_registry():
    """El optimizador evalúa candidatos que aún no son arquetipos registrados."""
    from mistsim.sim.batch import run_batch

    tuned = archetypes.get("aggro-combate").clone(name="candidato", cost_bias=0.9)
    spec = _spec(strategies=("candidato", "rush-mision"),
                 custom_profiles=(("candidato", tuned),))
    results = list(run_batch(spec, 4, workers=1, collect_log=False))
    assert len(results) == 4
    assert all(r.players[0].strategy == "candidato" for r in results)


def test_empty_batch_yields_nothing():
    from mistsim.sim.batch import run_batch

    assert list(run_batch(_spec(), 0)) == []


def test_batch_output_feeds_the_corpus_writer(tmp_path):
    """El encadenado que usará la minería de combos: lote -> JSONL, sin memoria de por medio."""
    from mistsim.sim.batch import run_batch

    path = tmp_path / "corpus.jsonl"
    written = serial.write_corpus(
        path, run_batch(_spec(), 10, workers=1, collect_log=False))
    assert written == 10
    assert sum(1 for _ in serial.read_corpus_dicts(path)) == 10


# --- A5: CLI extensible ------------------------------------------------------


def test_every_command_module_registers_itself():
    """Un comando nuevo se añade creando un fichero, sin tocar main.py."""
    from mistsim.cli import commands

    names = {m.__name__.rsplit(".", 1)[-1] for m in commands.discover()}
    assert {"play", "batch", "tourney", "validate", "cards"} <= names


def test_parser_exposes_all_discovered_commands():
    from mistsim.cli import commands
    from mistsim.cli.main import build_parser

    parser = build_parser()
    action = next(a for a in parser._actions if a.dest == "command")
    discovered = {m.__name__.rsplit(".", 1)[-1] for m in commands.discover()}
    assert discovered <= set(action.choices)


def test_cli_runs_end_to_end(capsys):
    from mistsim.cli.main import main

    assert main(["validate"]) == 0
    assert "Contenido válido" in capsys.readouterr().out

    assert main(["cards", "Rebel"]) == 0
    assert "riot" in capsys.readouterr().out


def test_result_records_its_mode_and_player_count(content):
    """El análisis estratifica por modo; deducirlo del motivo de fin es frágil."""
    from mistsim.agents.utility import make

    for mode, expected in ((Mode.PVP, "pvp"), (Mode.COOP, "coop")):
        engine = GameEngine(content=content,
                            config=GameConfig(mode=mode, num_players=3, max_turns=15),
                            seed=2)
        result = engine.run([make("equilibrado", i) for i in range(3)])
        assert result.mode == expected
        assert result.num_players == 3

        back = serial.result_from_dict(serial.result_to_dict(result))
        assert (back.mode, back.num_players) == (expected, 3)
