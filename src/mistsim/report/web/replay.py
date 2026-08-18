"""Reconstruye, evento a evento, el estado que necesita el reproductor de partida.

El log no guarda una foto fija del estado por turno —eso duplicaría `GameState`, que ya
tiene su propio contrato de clonado en `domain/state.py`—. Lo que sí guarda es *todo* lo
que cambia el estado, así que este módulo hace lo mismo que `report/log.py`: recorrer el
log una vez y derivar lo que hace falta, sin volver a tocar el motor ni reimplementar sus
reglas.

Limitación explícita, y a propósito no se disimula: el log no registra el CONTENIDO de
la mano turno a turno (sólo cuántas cartas se roban) ni la composición exacta de la fila
del Mercado en cada instante. El reproductor lo dice en la propia página en vez de
inventar esos datos — es la misma política de honestidad sobre datos que ya sigue el
resto del repo con las Misiones homebrew.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mistsim.domain.metals import BASE_METALS
from mistsim.domain.player import MAX_HEALTH
from mistsim.engine.events import Event
from mistsim.engine.game import GameResult
from mistsim.engine.setup import BASE_HEALTH, TURN_ORDER_HEALTH
from mistsim.report.log import ATTRIBUTED_TO_ACTOR, NOISY, describe

TOKEN_READY = "ready"
TOKEN_BURNED = "burned"
TOKEN_FLARED = "flared"


def _owner_of(event: Event) -> int | None:
    """Mismo criterio que `report.log.render`: un evento sufrido por la víctima pero
    causado por otro jugador se agrupa en el bloque de quien lo causa."""
    if event.kind in ATTRIBUTED_TO_ACTOR:
        actor = event.data.get("by")
        return actor if actor is not None else event.player
    return event.player


@dataclass
class Block:
    """Un tramo de eventos de un (turno, jugador) — o el arranque de la partida."""

    turn: int
    owner: int | None
    events: list[Event] = field(default_factory=list)
    #: id de jugador -> estado derivado justo después de este bloque.
    snapshot: dict[int, dict[str, Any]] = field(default_factory=dict)


def _new_player_state(player_id: int) -> dict[str, Any]:
    return {
        "id": player_id,
        "health": None,
        "training": 0,
        "metals": dict.fromkeys((str(m) for m in BASE_METALS), TOKEN_READY),
        "tracks": {},
        "purchases": [],
    }


def _copy_player_state(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"], "health": p["health"], "training": p["training"],
        "metals": dict(p["metals"]), "tracks": dict(p["tracks"]),
        "purchases": list(p["purchases"]),
    }


def _apply(event: Event, state: dict[int, dict[str, Any]], track_names: list[str]) -> None:
    data = event.data
    kind = event.kind

    if kind == "game-start":
        for name in data.get("missions") or []:
            if name not in track_names:
                track_names.append(name)
        # La salud inicial no llega en ningun evento propio (el primer
        # `turn-start` de cada jugador es lo primero que la trae), pero se
        # conoce con certeza: es la formula real del motor, no una suposicion.
        # En Coop nadie recibe el bonus por orden de turno.
        coop = data.get("mode") == "coop"
        for player_id, player_state in state.items():
            bonus = 0 if coop else TURN_ORDER_HEALTH.get(player_id, 4)
            player_state["health"] = BASE_HEALTH + bonus
        return

    player = state.get(event.player) if event.player is not None else None
    if player is None:
        return

    if kind == "turn-start":
        player["health"] = data.get("health", player["health"])
        player["training"] = data.get("training", player["training"])
        for metal, st in player["metals"].items():
            if st == TOKEN_BURNED:
                player["metals"][metal] = TOKEN_READY
    elif kind == "burn":
        if "metal" in data:
            player["metals"][data["metal"]] = TOKEN_BURNED
    elif kind == "flare":
        if "metal" in data:
            player["metals"][data["metal"]] = TOKEN_FLARED
    elif kind == "refresh":
        if "metal" in data:
            player["metals"][data["metal"]] = TOKEN_BURNED
    elif kind == "damage":
        if "health" in data:
            player["health"] = data["health"]
    elif kind == "heal":
        if player["health"] is not None:
            player["health"] = min(MAX_HEALTH, player["health"] + data.get("amount", 0))
    elif kind == "turn-end":
        player["health"] = data.get("health", player["health"])
    elif kind == "mission-advance":
        track = data.get("track")
        if track is not None:
            if track not in track_names:
                track_names.append(track)
            player["tracks"][track] = data.get("to", player["tracks"].get(track, 0))
    elif kind == "buy":
        card = data.get("card")
        if card is not None:
            player["purchases"].append(card)


def build_timeline(result: GameResult) -> dict[str, Any]:
    """Devuelve `{blocks, tracks, num_players}` para un `GameResult`.

    `blocks` es la secuencia de pasos que recorre el reproductor: uno por el arranque
    de la partida y uno por cada tramo (turno, jugador) del log, agrupados con el mismo
    criterio que `report.log.render` usa para imprimirlos.
    """
    state = {p.player_id: _new_player_state(p.player_id) for p in result.players}
    track_names: list[str] = []
    blocks: list[Block] = []
    current_key: tuple[int, int | None] | None = None

    for event in result.log:
        if event.kind == "game-start":
            block = Block(turn=0, owner=None)
            blocks.append(block)
            block.events.append(event)
            _apply(event, state, track_names)
            block.snapshot = {pid: _copy_player_state(p) for pid, p in state.items()}
            current_key = None  # fuerza a que el siguiente evento abra bloque propio
            continue

        key = (event.turn, _owner_of(event))
        if key != current_key:
            current_key = key
            blocks.append(Block(turn=key[0], owner=key[1]))
        block = blocks[-1]
        block.events.append(event)
        _apply(event, state, track_names)
        block.snapshot = {pid: _copy_player_state(p) for pid, p in state.items()}

    return {
        "blocks": [_block_to_dict(b) for b in blocks],
        "tracks": track_names,
        "num_players": len(result.players),
    }


def _block_to_dict(block: Block) -> dict[str, Any]:
    return {
        "turn": block.turn,
        "owner": block.owner,
        "events": [
            {
                "kind": e.kind,
                "player": e.player,
                "desc": describe(e),
                "noisy": e.kind in NOISY,
                "data": dict(e.data),
            }
            for e in block.events
        ],
        "snapshot": block.snapshot,
    }
