"""Etiquetas derivadas de los efectos de cada carta.

Se calculan de los datos en vez de escribirse a mano: si una carta cambia, su papel
cambia solo. Son la base sobre la que las estrategias razonan, en lugar de listas de
nombres codificadas.
"""
from __future__ import annotations

from enum import StrEnum

from mistsim.domain.cards import Card, Effects
from mistsim.domain.metals import Metal


class Tag(StrEnum):
    COMBAT = "combat"            # produce daño
    MISSION = "mission"          # produce puntos de misión
    ECONOMY = "economy"          # produce monedas
    DRAW = "draw"                # roba cartas
    HEAL = "heal"                # cura
    THINNER = "thinner"          # elimina cartas propias (adelgaza el mazo)
    DEFENDER = "defender"        # protege al jugador
    RECURSION = "recursion"      # recupera del descarte o de las eliminadas
    MARKET_CONTROL = "market"    # manipula el Mercado (Push, comprar dirigido)
    ENABLER = "enabler"          # hace actuar a otras cartas (Riot, Seek)
    ALLY = "ally"
    ATIUM = "atium"
    TRAIN = "train"              # avanza la pista de Entrenamiento
    TRACK_AWARE = "track_aware"  # su valor depende de tu posición en las Misiones
    SCALING = "scaling"          # convierte o multiplica recursos
    REMOVAL = "removal"          # mata Aliados rivales

#: Efecto -> etiquetas que aporta.
_EFFECT_TAGS: dict[str, tuple[Tag, ...]] = {
    "combat": (Tag.COMBAT,),
    "mission": (Tag.MISSION,),
    "coin": (Tag.ECONOMY,),
    "draw": (Tag.DRAW,),
    "heal": (Tag.HEAL,),
    "train": (Tag.TRAIN,),
    "atium": (Tag.ATIUM,),
    "soothe": (Tag.THINNER,),
    "push": (Tag.MARKET_CONTROL,),
    "pull": (Tag.RECURSION,),
    "seek": (Tag.ENABLER, Tag.MARKET_CONTROL),
    "seek_two_different_cards": (Tag.ENABLER, Tag.MARKET_CONTROL),
    "riot": (Tag.ENABLER,),
    "sense": (Tag.TRACK_AWARE,),
    "cloud": (Tag.DEFENDER,),
    "cloud_protect_ally": (Tag.DEFENDER,),
    "kill_ally": (Tag.REMOVAL,),
    "kill_all_opponent_allies": (Tag.REMOVAL,),
    "convert_all_mission_to_combat": (Tag.SCALING, Tag.COMBAT),
    "convert_all_combat_to_mission": (Tag.SCALING, Tag.MISSION),
    "combat_per_highest_mission_track": (Tag.SCALING, Tag.COMBAT, Tag.TRACK_AWARE),
    "coin_per_lowest_mission_track": (Tag.SCALING, Tag.ECONOMY, Tag.TRACK_AWARE),
    "draw_per_highest_mission_track": (Tag.SCALING, Tag.DRAW, Tag.TRACK_AWARE),
    "draw_if_lowest_on_any_mission_track": (Tag.DRAW, Tag.TRACK_AWARE),
    "advance_mission_track_if_lowest_all": (Tag.MISSION, Tag.TRACK_AWARE),
    "gain_eliminated_card_to_discard": (Tag.RECURSION,),
    "gain_eliminated_card_to_hand": (Tag.RECURSION,),
    "may_buy_eliminated_card": (Tag.RECURSION, Tag.MARKET_CONTROL),
    "play_top_ability_of_eliminated_card": (Tag.RECURSION,),
    "gain_market_card_to_discard_max_cost": (Tag.MARKET_CONTROL,),
    "eliminate_all_market_cards": (Tag.MARKET_CONTROL,),
    "look_top_deck_eliminate_or_return": (Tag.THINNER,),
    "set_aside_hand_card_draw_next_turn": (Tag.DRAW,),
    "repeat_own_top_ability": (Tag.SCALING, Tag.ENABLER),
    "refresh_any_flared_metal": (Tag.ENABLER,),
    "win_game": (Tag.ATIUM,),
}

_ONGOING_TAGS: dict[str, tuple[Tag, ...]] = {
    "defender": (Tag.DEFENDER,),
    "draw_extra_card_on_hand_draw": (Tag.DRAW,),
    "extra_metal_burn": (Tag.ENABLER,),
    "reduce_damage_taken_by_1": (Tag.DEFENDER,),
}


def _scan(effects: Effects | None, out: set[Tag]) -> None:
    if not effects:
        return
    for key, value in effects.items():
        out.update(_EFFECT_TAGS.get(key, ()))
        if key == "choice_of" and isinstance(value, list):
            for option in value:
                out.update(_EFFECT_TAGS.get(option.split(":")[0], ()))
        if key in ("combat_or_coin_choice",):
            out.update((Tag.COMBAT, Tag.ECONOMY))


def tags_for(card: Card) -> frozenset[Tag]:
    out: set[Tag] = set()
    for ability in (card.primary, card.secondary):
        if ability:
            _scan(ability.effects, out)
    _scan(card.savant, out)
    _scan(card.off_turn, out)
    out.update(_ONGOING_TAGS.get(card.ongoing or "", ()))
    if card.is_ally:
        out.add(Tag.ALLY)
    if Metal.ATIUM in card.metal_pair:
        out.add(Tag.ATIUM)
    return frozenset(out)


def output_value(card: Card) -> dict[str, int]:
    """Cuánto produce la carta de cada recurso, sumando primaria y secundaria.

    Es una aproximación cruda a propósito: no descuenta el coste de activar la
    secundaria. Ese descuento lo aplica el scoring, que sí conoce el mazo del jugador.
    """
    totals: dict[str, int] = {}
    for ability in (card.primary, card.secondary):
        if not ability:
            continue
        for key, value in ability.effects.items():
            if isinstance(value, int) and key in ("combat", "mission", "coin", "heal", "draw"):
                totals[key] = totals.get(key, 0) + value
    return totals
