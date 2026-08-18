"""Serialización de partidas, logs y perfiles.

Contrato congelado en la Fase A: la minería de combos persiste corpus con esto, el
visor web se alimenta de esto, y el optimizador guarda aquí sus poblaciones. Cambiar
estas funciones rompe a los tres, así que se añaden campos pero no se renombran.

El formato de corpus es JSONL —una partida por línea— para poder escribir en streaming
durante un lote largo y leerlo después sin cargarlo entero en memoria.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from mistsim.agents.profile import StrategyProfile
from mistsim.agents.tags import Tag
from mistsim.domain.metals import Metal
from mistsim.engine.events import Event, EventLog
from mistsim.engine.game import GameResult, PlayerResult

SCHEMA_VERSION = 1


# --- eventos -----------------------------------------------------------------


def event_to_dict(event: Event) -> dict[str, Any]:
    return {"kind": event.kind, "turn": event.turn, "player": event.player,
            "data": event.data}


def event_from_dict(raw: dict[str, Any]) -> Event:
    return Event(kind=raw["kind"], turn=raw["turn"], player=raw.get("player"),
                 data=raw.get("data") or {})


def log_to_list(log: EventLog) -> list[dict[str, Any]]:
    return [event_to_dict(e) for e in log]


def log_from_list(raw: list[dict[str, Any]]) -> EventLog:
    log = EventLog()
    log.events = [event_from_dict(e) for e in raw]
    log.turn = log.events[-1].turn if log.events else 0
    return log


# --- resultados --------------------------------------------------------------


def player_to_dict(pr: PlayerResult) -> dict[str, Any]:
    return {
        "player_id": pr.player_id, "strategy": pr.strategy, "character": pr.character,
        "won": pr.won, "rank": pr.rank, "final_health": pr.final_health,
        "purchases": list(pr.purchases), "damage_dealt": pr.damage_dealt,
        "damage_taken": pr.damage_taken, "mission_points_spent": pr.mission_points_spent,
        "tracks_topped": pr.tracks_topped, "cards_eliminated": pr.cards_eliminated,
        "training": pr.training,
    }


def player_from_dict(raw: dict[str, Any]) -> PlayerResult:
    return PlayerResult(**raw)


def result_to_dict(result: GameResult, *, include_log: bool = True) -> dict[str, Any]:
    """Serializa una partida.

    `include_log=False` deja fuera el log de eventos, que es con diferencia lo más
    pesado. Un corpus para minería de combos sólo necesita los datos por jugador; el
    visor web sí necesita el log.
    """
    out: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "winner": result.winner,
        "reason": result.reason,
        "turns": result.turns,
        "final_health": {str(k): v for k, v in result.final_health.items()},
        "mission_positions": {
            track: {str(p): v for p, v in positions.items()}
            for track, positions in result.mission_positions.items()
        },
        "players": [player_to_dict(p) for p in result.players],
    }
    if include_log:
        out["log"] = log_to_list(result.log)
    return out


def result_from_dict(raw: dict[str, Any]) -> GameResult:
    return GameResult(
        winner=raw.get("winner"),
        reason=raw["reason"],
        turns=raw["turns"],
        log=log_from_list(raw.get("log") or []),
        final_health={int(k): v for k, v in (raw.get("final_health") or {}).items()},
        mission_positions={
            track: {int(p): v for p, v in positions.items()}
            for track, positions in (raw.get("mission_positions") or {}).items()
        },
        players=[player_from_dict(p) for p in raw.get("players") or []],
    )


# --- perfiles de estrategia --------------------------------------------------


def profile_to_dict(profile: StrategyProfile) -> dict[str, Any]:
    """Los perfiles usan enums Metal y Tag como claves; JSON exige cadenas."""
    return {
        "name": profile.name,
        "description": profile.description,
        "weights": dict(profile.weights),
        "metal_affinity": {str(m): v for m, v in profile.metal_affinity.items()},
        "tag_affinity": {t.value: v for t, v in profile.tag_affinity.items()},
        "synergy_weight": profile.synergy_weight,
        "cost_bias": profile.cost_bias,
        "mission_focus": profile.mission_focus,
        "panic_health": profile.panic_health,
    }


def profile_from_dict(raw: dict[str, Any]) -> StrategyProfile:
    return StrategyProfile(
        name=raw["name"],
        description=raw.get("description", ""),
        weights=dict(raw.get("weights") or {}),
        metal_affinity={Metal(m): v for m, v in (raw.get("metal_affinity") or {}).items()},
        tag_affinity={Tag(t): v for t, v in (raw.get("tag_affinity") or {}).items()},
        synergy_weight=raw.get("synergy_weight", 1.0),
        cost_bias=raw.get("cost_bias", 0.0),
        mission_focus=raw.get("mission_focus", 0.5),
        panic_health=raw.get("panic_health", 12),
    )


# --- corpus JSONL ------------------------------------------------------------


def write_corpus(path: str | Path, results: Iterable[GameResult], *,
                 include_log: bool = False, append: bool = False) -> int:
    """Escribe partidas como JSONL, una por línea. Devuelve cuántas escribió.

    Consume `results` de forma perezosa, así que un lote de 100 000 partidas nunca está
    entero en memoria.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a" if append else "w", encoding="utf-8") as fh:
        for result in results:
            fh.write(json.dumps(result_to_dict(result, include_log=include_log),
                                ensure_ascii=False) + "\n")
            count += 1
    return count


def read_corpus(path: str | Path) -> Iterator[GameResult]:
    """Lee un corpus JSONL de forma perezosa."""
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield result_from_dict(json.loads(line))


def read_corpus_dicts(path: str | Path) -> Iterator[dict[str, Any]]:
    """Igual que read_corpus pero sin reconstruir objetos.

    Para agregaciones grandes es bastante más rápido: la minería de combos sólo mira
    `players[].purchases` y `players[].won`, y no necesita el resto reconstruido.
    """
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
