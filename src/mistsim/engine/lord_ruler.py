"""Modo Solo/Cooperativo: el mazo de desafíos del Lord Ruler.

OJO: las 36 cartas son homebrew (data/lord_ruler.json). La estructura sí sigue el manual
y el FAQ, pero los valores concretos son inventados, así que un resultado de este modo
no es un resultado del juego real.
"""
from __future__ import annotations

from mistsim.domain.player import Player
from mistsim.domain.state import GameState
from mistsim.engine.choices import Chooser
from mistsim.engine.effects import EffectContext, resolve
from mistsim.engine.events import EventLog

HEAL_PER_INCOMPLETE_MISSION = 10
MAX_LORD_RULER_HEALTH = 48
MARKET_CARDS_CLEARED = 2


def resolve_challenge(state: GameState, player: Player, log: EventLog,
                      chooser: Chooser) -> None:
    """Tras el turno de cada jugador, se revela y resuelve la siguiente carta."""
    lr = state.lord_ruler
    if lr is None or state.finished:
        return
    if not lr.deck:
        state.finished = True
        state.victory_reason = "lord-ruler-deck-empty"
        log.emit("defeat", None, reason="lord-ruler-deck-empty")
        return

    card = lr.deck.pop()
    if card["type"] == "Adversary":
        _deploy_adversary(state, player, card, log)
    else:
        _resolve_edict(state, player, card, log, chooser)

    _resolve_end_of_turn_adversaries(state, player, log, chooser)


def _deploy_adversary(state: GameState, player: Player, card: dict,
                      log: EventLog) -> None:
    """Entra en juego asignado a un jugador, con sus escudos intactos."""
    lr = state.lord_ruler
    lr.adversaries.append(card)
    lr.shields[card["id"]] = list(card["shields"])
    lr.assigned_to[card["id"]] = player.id
    log.emit("adversary-revealed", player.id, adversary=card["name"],
             shields=[lr.shield_value(s) for s in card["shields"]],
             timing=card["timing"])


def _resolve_edict(state: GameState, player: Player, card: dict, log: EventLog,
                   chooser: Chooser) -> None:
    """Un Edicto encadena hasta 4 efectos, siempre en el mismo orden."""
    lr = state.lord_ruler
    log.emit("edict", player.id, edict=card["name"])

    # 1. Sube la Dominance, que es lo que endurece los escudos "X".
    raised = lr.raise_dominance(card.get("dominance_increase", 0))
    if raised:
        log.emit("dominance", None, to=lr.dominance)

    # 2. Efecto negativo.
    effect = card.get("effect") or {}
    if "collective_damage" in effect:
        _collective_damage(state, effect["collective_damage"], log, chooser)
    elif effect:
        ctx = EffectContext(state, player, log, chooser, source=f"edict:{card['name']}")
        resolve(effect, ctx)

    # 3. Se cura 10 por cada Misión que nadie haya completado.
    if card.get("heals_lord_ruler"):
        incomplete = sum(1 for t in state.tracks if not t.completed_by_anyone())
        healed = min(MAX_LORD_RULER_HEALTH - lr.health,
                     incomplete * HEAL_PER_INCOMPLETE_MISSION)
        if healed > 0:
            lr.health += healed
            log.emit("lord-ruler-heal", None, amount=healed, health=lr.health,
                     incomplete_missions=incomplete)

    # 4. Limpia cartas del Mercado, que se reponen al instante.
    if card.get("clears_market"):
        for _ in range(MARKET_CARDS_CLEARED):
            if not state.market.row:
                break
            removed = state.market.row[0]
            state.market.take(removed)
            state.eliminated.append(removed)
            log.emit("market-cleared", None, card=removed.name)


def _collective_damage(state: GameState, amount: int, log: EventLog,
                       chooser: Chooser) -> None:
    """Daño compartido: el grupo decide cómo repartirlo. En solitario se lo come uno."""
    alive = state.alive()
    if not alive:
        return
    remaining = amount
    while remaining > 0 and alive:
        victim_id = chooser.choose_player([p.id for p in alive], "collective-damage")
        victim = state.player(victim_id)
        share = remaining if len(alive) == 1 else max(1, remaining // len(alive))
        victim.take_damage(share)
        remaining -= share
        log.emit("damage", victim.id, amount=share, by=None, source="collective",
                 health=victim.health)
        alive = state.alive()


def _resolve_end_of_turn_adversaries(state: GameState, player: Player, log: EventLog,
                                     chooser: Chooser) -> None:
    """Los Adversarios de efecto "end_of_turn" castigan al jugador al que se asignaron."""
    lr = state.lord_ruler
    for adv in list(lr.adversaries):
        if adv["timing"] != "end_of_turn":
            continue
        if lr.assigned_to.get(adv["id"]) != player.id:
            continue
        ctx = EffectContext(state, player, log, chooser, source=f"adversary:{adv['name']}")
        resolve(adv["effect"], ctx)


def permanent_penalties(state: GameState, player: Player) -> dict[str, int]:
    """Penalizaciones permanentes de los Adversarios asignados a este jugador.

    Se consultan al calcular acciones legales, no se aplican una vez: un Adversario
    con efecto permanente estorba mientras siga vivo.
    """
    lr = state.lord_ruler
    if lr is None:
        return {}
    out: dict[str, int] = {}
    for adv in lr.adversaries:
        if adv["timing"] != "permanent":
            continue
        if lr.assigned_to.get(adv["id"]) != player.id:
            continue
        for key, value in (adv.get("effect") or {}).items():
            out[key] = out.get(key, 0) + (1 if value is True else int(value))
    return out
