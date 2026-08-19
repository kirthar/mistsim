"""Reacciones fuera de turno.

Seis cartas del Mercado tienen habilidad `off_turn`, y ninguna la tiene en su primaria ni
en su secundaria: **existen sólo como reacción durante el turno ajeno**. Sin una ventana
de reacción, dos de los ocho keywords de metal —`Sense` (Estaño) y `Cloud` (Cobre)— no
ocurren nunca, y son 9 de las 82 cartas físicas.

El texto impreso manda sobre la descripción del keyword en el manual. `metals.json` decía
que Sense "impide avanzar en una pista de Misión"; las cartas dicen otra cosa:

    Spy        SENSE 3   "Play off turn to reduce an opponent's [misión] by 3."
    Eavesdrop  SENSE 2   "Play off turn to reduce an opponent's [misión] by 2."
    Sneak      CLOUD 3   "Play off-turn to reduce incoming [daño] to you or another
                          player by 3."
    Hide       CLOUD     "Play off-turn to prevent an Ally from being eliminated.
                          The attacking [daño] is still spent."

Jugar una reacción no exige quemar metal: es la habilidad de fuera de turno de la carta.
La carta sale de la mano y va al descarte de su dueño.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mistsim.domain.cards import CardInstance
from mistsim.domain.player import Player
from mistsim.domain.state import GameState
from mistsim.engine.events import EventLog


class Trigger(StrEnum):
    """Momentos en que se abre una ventana de reacción."""

    INCOMING_DAMAGE = "incoming_damage"    # Cloud: reducir daño a un jugador
    ALLY_DOOMED = "ally_doomed"            # Cloud de Hide: salvar a un Aliado
    MISSION_SPENDING = "mission_spending"  # Sense: recortar la misión del rival


#: Qué clave de `off_turn` responde a cada disparador.
_KEYS: dict[Trigger, tuple[str, ...]] = {
    Trigger.INCOMING_DAMAGE: ("cloud",),
    Trigger.ALLY_DOOMED: ("cloud_protect_ally",),
    Trigger.MISSION_SPENDING: ("sense",),
}


@dataclass
class ReactionContext:
    """Lo que un agente necesita saber para decidir si gasta una carta de la mano."""

    trigger: Trigger
    #: Jugador que puede reaccionar.
    reactor: int
    #: Jugador al que le pasa algo (el que recibe el daño, el dueño del Aliado…).
    subject: int
    #: Magnitud en juego: daño entrante, defensa del Aliado, o misión que se va a gastar.
    amount: int = 0
    #: Aliado en peligro, cuando aplica.
    ally: CardInstance | None = None


def candidates(player: Player, trigger: Trigger) -> list[CardInstance]:
    """Cartas de la mano que pueden jugarse como reacción a este disparador."""
    keys = _KEYS[trigger]
    return [
        inst for inst in player.hand
        if inst.card.off_turn and any(k in inst.card.off_turn for k in keys)
    ]


def contribution(inst: CardInstance, trigger: Trigger) -> int:
    """Cuánto aporta esta carta al disparador. `cloud_protect_ally` no lleva número."""
    off = inst.card.off_turn or {}
    for key in _KEYS[trigger]:
        raw = off.get(key)
        if raw is True:
            return 1
        if isinstance(raw, int):
            return raw
    return 0


def _spend(state: GameState, player: Player, inst: CardInstance, log: EventLog,
           context: ReactionContext) -> int:
    player.hand.remove(inst)
    player.discard.append(inst)
    amount = contribution(inst, context.trigger)
    log.emit("reaction", player.id, card=inst.name, trigger=str(context.trigger),
             amount=amount, subject=context.subject)
    return amount


def offer(state: GameState, trigger: Trigger, subject: int, amount: int,
          agents: list, log: EventLog, *, ally: CardInstance | None = None,
          reactors: list[int] | None = None) -> int:
    """Abre una ventana de reacción y devuelve el total aportado.

    Pregunta a cada jugador que pueda reaccionar, en orden de asiento. Un jugador puede
    encadenar varias cartas mientras le queden y siga queriendo: cada una es una decisión
    aparte, que es como funciona en mesa.

    `agents` viene indexado por asiento; los agentes que no implementen `choose_reaction`
    heredan el que no reacciona nunca, así que añadir esto no cambia a nadie que no opine.
    """
    total = 0
    seats = reactors if reactors is not None else [p.id for p in state.alive()]

    for seat in seats:
        player = state.player(seat)
        agent = agents[seat] if seat < len(agents) else None
        if agent is None or not hasattr(agent, "choose_reaction"):
            continue

        while True:
            options = candidates(player, trigger)
            if not options:
                break
            context = ReactionContext(trigger=trigger, reactor=seat, subject=subject,
                                      amount=max(0, amount - total), ally=ally)
            chosen = agent.choose_reaction(state, options, context)
            if chosen is None:
                break
            total += _spend(state, player, chosen, log, context)
            # Salvar a un Aliado o anular el daño por completo no admite más cartas.
            if trigger is Trigger.ALLY_DOOMED or total >= amount:
                return total
    return total
