"""Acciones legales dentro de un turno.

El turno real es "en cualquier orden y cualquier número de veces", así que el motor no
lo codifica como un guion: expone `legal_actions(state)` y `apply(state, action)`.

Ésta es la decisión de diseño que sostiene todo lo demás. Un agente elige acciones de
esa lista; el solver de turno óptimo la recorrerá en profundidad; y un MCTS la usará
como espacio de ramificación. Si el turno fuera un guion fijo, nada de eso sería
posible sin reescribir el motor.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mistsim.domain.cards import CardInstance
from mistsim.domain.metals import Metal
from mistsim.domain.state import GameState


class ActionKind(StrEnum):
    PLAY_CARD = "play_card"          # jugar una carta boca arriba en la zona de juego
    BURN = "burn"                    # quemar una ficha de metal
    FLARE = "flare"                  # voltear una ficha para saltarse el límite
    CARD_AS_METAL = "card_as_metal"  # jugar una carta de lado como metal
    REFRESH = "refresh"              # descartar una carta para desflarear un metal
    ACTIVATE = "activate"            # activar primaria/secundaria de una carta en juego
    ACTIVATE_ALLY = "activate_ally"  # activar un Aliado por su metal
    CHARACTER = "character"          # habilidad de personaje (Nivel I)
    BUY = "buy"                      # comprar del Mercado
    BUY_BOXING = "buy_boxing"
    SELL_BOXING = "sell_boxing"
    ADVANCE_MISSION = "advance_mission"
    END_TURN = "end_turn"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    card: CardInstance | None = None
    metal: Metal | None = None
    #: "primary" o "secondary" en ACTIVATE.
    tier: str | None = None
    #: Índice de pista en ADVANCE_MISSION.
    track: int | None = None
    #: Puntos de misión a gastar en esa pista.
    amount: int = 0
    #: Carta que se descarta para refrescar.
    payment: CardInstance | None = None

    def __str__(self) -> str:
        bits = [self.kind.value]
        if self.card is not None:
            bits.append(self.card.name)
        if self.metal is not None:
            bits.append(str(self.metal))
        if self.tier:
            bits.append(self.tier)
        if self.track is not None:
            bits.append(f"track{self.track}+{self.amount}")
        return " ".join(bits)


def legal_actions(state: GameState) -> list[Action]:
    """Todas las acciones legales ahora mismo para el jugador activo."""
    player = state.player(state.active)
    actions: list[Action] = [Action(ActionKind.END_TURN)]
    tokens = player.tokens

    # Jugar cartas de la mano boca arriba. Un Aliado va a la zona de Aliados y se queda;
    # una Acción va a la zona de juego y se descarta al final del turno.
    for inst in player.hand:
        actions.append(Action(ActionKind.PLAY_CARD, card=inst))

    # Jugar una carta de lado como metal. No consume quema de ficha (FAQ), y puede
    # hacerse sin alimentar nada, sólo para disparar Aliados, personaje o savant.
    for inst in player.hand:
        for metal in inst.card.playable_as_metal():
            actions.append(Action(ActionKind.CARD_AS_METAL, card=inst, metal=metal))

    # Quemar fichas, dentro del límite del turno.
    for metal in tokens.state:
        if tokens.can_burn(metal):
            actions.append(Action(ActionKind.BURN, metal=metal))

    # Flarear para pasarse del límite: sólo fichas sin usar todavía (FAQ).
    for metal in tokens.state:
        if tokens.can_flare(metal):
            actions.append(Action(ActionKind.FLARE, metal=metal))

    # Refrescar: descartar una carta cuyo vial case con el metal flareado.
    # Los Aliados nunca sirven para esto (FAQ).
    for metal in tokens.flared():
        for inst in player.hand:
            if metal in inst.card.playable_as_metal():
                actions.append(Action(ActionKind.REFRESH, metal=metal, payment=inst))

    # Activar habilidades de cartas ya en juego.
    for inst in player.in_play:
        actions.extend(_activation_actions(state, inst))
    for ally in player.allies:
        actions.extend(_ally_actions(state, ally))

    # Habilidad de personaje: una vez por turno, con su metal insignia quemado.
    if "character" not in player.used_once_per_turn:
        signature = Metal(player.character.signature_metal)
        if _metal_active(state, signature):
            actions.append(Action(ActionKind.CHARACTER, metal=signature))

    # Comprar. Sin límite de compras por turno más allá de las monedas.
    for inst in state.market.affordable(player.resources.coin):
        actions.append(Action(ActionKind.BUY, card=inst))
    if player.resources.coin >= 2:
        actions.append(Action(ActionKind.BUY_BOXING))
    if player.boxings > 0:
        actions.append(Action(ActionKind.SELL_BOXING))

    # Gastar puntos de misión. Se pueden repartir entre pistas o volcar todos en una.
    if player.resources.mission > 0:
        for idx, track in enumerate(state.tracks):
            if track.finisher == player.id:
                continue
            for amount in range(1, player.resources.mission + 1):
                actions.append(Action(ActionKind.ADVANCE_MISSION, track=idx, amount=amount))

    return actions


def _metal_active(state: GameState, metal: Metal | None) -> bool:
    """¿Se ha quemado o jugado ese metal este turno?

    Cubre tanto la ficha quemada como una carta jugada de lado, porque ambas cuentan
    igual para disparar Aliados y la habilidad de personaje.

    `metal is None` significa que la habilidad no exige metal alguno — es el caso de
    las cartas de Financiación, que dan su moneda con sólo jugarlas.
    """
    if metal is None:
        return True
    return metal in state.player(state.active).metals_active_this_turn


def _activation_actions(state: GameState, inst: CardInstance) -> list[Action]:
    card = inst.card
    out: list[Action] = []
    if card.primary and not inst.primary_activated and _metal_active(state, card.primary.metal):
        out.append(Action(ActionKind.ACTIVATE, card=inst, tier="primary"))
    # La secundaria exige haber activado antes la primaria, y N quemas adicionales.
    if (card.secondary and inst.primary_activated
            and "secondary" not in inst.activations_used
            and _burns_available(state, card.secondary.metal, card.secondary.extra_burns)):
        out.append(Action(ActionKind.ACTIVATE, card=inst, tier="secondary"))
    return out


def _ally_actions(state: GameState, ally: CardInstance) -> list[Action]:
    card = ally.card
    out: list[Action] = []
    if (card.primary and "burn" not in ally.activations_used
            and _metal_active(state, card.primary.metal)):
        out.append(Action(ActionKind.ACTIVATE_ALLY, card=ally, tier="primary"))
    if (card.secondary and "burn" in ally.activations_used
            and "secondary" not in ally.activations_used
            and _burns_available(state, card.secondary.metal, card.secondary.extra_burns)):
        out.append(Action(ActionKind.ACTIVATE_ALLY, card=ally, tier="secondary"))
    return out


def _burns_available(state: GameState, metal: Metal | None, needed: int) -> bool:
    """¿Se han acumulado ya las N quemas extra de ese metal este turno?"""
    if metal is None:
        return True
    player = state.player(state.active)
    return player.metal_burn_counts.get(metal, 0) >= needed + 1
