"""Sinergias entre cartas.

Este módulo es la respuesta a "no limitarse a juntar los metales del personaje". Una
carta no vale lo mismo en el vacío que junto a las que ya tienes: `Dominate` sólo brilla
con muchas fuentes de misión, `Rebel` escala con cada Aliado, `Ascendant` quiere cartas
caras que rescatar. El valor de compra es `valor_base + sinergia_con_lo_que_ya_tienes`.

Las reglas son pocas y explícitas a propósito: cada una responde a una interacción
mecánica concreta, no a una intuición. El optimizador de la 2ª entrega podrá luego
ajustar sus pesos o descubrir otras nuevas por minería de partidas.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mistsim.agents.tags import Tag, tags_for
from mistsim.domain.cards import Card
from mistsim.domain.metals import Metal


@dataclass(frozen=True)
class SynergyRule:
    name: str
    why: str
    #: ¿Se aplica esta regla a la carta candidata?
    applies: Callable[[Card], bool]
    #: Cuánto suma por cada carta ya poseída que la alimente.
    per_partner: float
    #: ¿Cuenta esta carta ya poseída como pareja?
    partner: Callable[[Card], bool]
    #: Tope, para que una sinergia no se dispare sin límite.
    cap: float = 6.0


def _has(tag: Tag) -> Callable[[Card], bool]:
    return lambda card: tag in tags_for(card)


def _named(*names: str) -> Callable[[Card], bool]:
    wanted = set(names)
    return lambda card: card.name in wanted


def _effect_in(card: Card, key: str) -> bool:
    return any(ability and key in ability.effects
               for ability in (card.primary, card.secondary))


def _pays_extra_burns(card: Card) -> bool:
    """¿Tiene una secundaria cara que justifique conseguir quemas de más?"""
    return card.secondary is not None and card.secondary.extra_burns >= 2


def _grants_extra_burns(card: Card) -> bool:
    return card.ongoing == "extra_metal_burn" or _effect_in(card, "refresh_any_flared_metal")


RULES: tuple[SynergyRule, ...] = (
    SynergyRule(
        name="riot-necesita-aliados",
        why="Riot activa un Aliado sin quemar su metal; sin Aliados no hace nada.",
        applies=lambda c: _effect_in(c, "riot"),
        partner=lambda c: c.is_ally and c.primary is not None,
        per_partner=1.4, cap=7.0,
    ),
    SynergyRule(
        name="aliados-quieren-riot",
        why="Cada fuente de Riot da a los Aliados una activación extra por turno.",
        applies=lambda c: c.is_ally and c.primary is not None,
        partner=lambda c: _effect_in(c, "riot"),
        per_partner=1.2, cap=4.0,
    ),
    SynergyRule(
        name="dominate-quiere-mision",
        why="Dominate convierte TODA la misión acumulada en combate: "
            "escala con las fuentes de misión.",
        applies=lambda c: _effect_in(c, "convert_all_mission_to_combat"),
        partner=_has(Tag.MISSION),
        per_partner=0.9, cap=8.0,
    ),
    SynergyRule(
        name="housewar-quiere-combate",
        why="House War convierte TODO el combate en misión: escala con las fuentes de daño.",
        applies=lambda c: _effect_in(c, "convert_all_combat_to_mission"),
        partner=_has(Tag.COMBAT),
        per_partner=0.9, cap=8.0,
    ),
    SynergyRule(
        name="confrontation-quiere-atium",
        why="Confrontation gana la partida con 4 Atium: sólo vale con generación de Atium.",
        applies=_named("Confrontation"),
        partner=lambda c: Metal.ATIUM in c.metal_pair,
        per_partner=2.5, cap=12.0,
    ),
    SynergyRule(
        name="pull-quiere-cartas-caras",
        why="Pull sube cartas del descarte al tope del mazo; sólo compensa con cartas potentes.",
        applies=lambda c: _effect_in(c, "pull"),
        partner=lambda c: c.cost >= 5,
        per_partner=0.7, cap=5.0,
    ),
    SynergyRule(
        name="adelgazar-quiere-mazo-gordo",
        why="Soothe elimina cartas propias; cuanto más relleno tienes, más sube la calidad media.",
        applies=_has(Tag.THINNER),
        partner=lambda c: c.cost <= 2,
        per_partner=0.5, cap=5.0,
    ),
    SynergyRule(
        name="robo-quiere-cartas-jugables",
        why="Robar sólo vale si hay a qué jugarlo; escala con la densidad de cartas activas.",
        applies=_has(Tag.DRAW),
        partner=lambda c: c.primary is not None and not c.is_ally,
        per_partner=0.25, cap=4.0,
    ),
    SynergyRule(
        name="quemas-extra-quieren-secundarias",
        why="Noble y compañía dan quemas de más; sólo valen con habilidades '+N METAL' que pagar.",
        applies=_grants_extra_burns,
        partner=_pays_extra_burns,
        per_partner=1.5, cap=6.0,
    ),
    SynergyRule(
        name="secundarias-caras-quieren-quemas",
        why="Una secundaria de '+2 METAL' es letra muerta sin quemas de sobra.",
        applies=_pays_extra_burns,
        partner=_grants_extra_burns,
        per_partner=1.5, cap=5.0,
    ),
    SynergyRule(
        name="defenders-protegen-aliados",
        why="Un Defender hace intocables al resto de tus Aliados, así que protege tu motor.",
        applies=_has(Tag.DEFENDER),
        partner=lambda c: c.is_ally and c.primary is not None,
        per_partner=0.8, cap=5.0,
    ),
    SynergyRule(
        name="recuperacion-quiere-eliminadas",
        why="Recuperar del montón de eliminadas sólo vale si tú mismo alimentas ese montón.",
        applies=_has(Tag.RECURSION),
        partner=_has(Tag.THINNER),
        per_partner=0.9, cap=4.0,
    ),
    SynergyRule(
        name="escalado-por-pista-quiere-mision",
        why="Los efectos que miden tu posición en las Misiones necesitan que la escales de verdad.",
        applies=_has(Tag.TRACK_AWARE),
        partner=_has(Tag.MISSION),
        per_partner=0.6, cap=5.0,
    ),
)


def synergy_score(candidate: Card, owned: list[Card]) -> float:
    """Valor extra de `candidate` por las cartas que el jugador ya tiene."""
    total = 0.0
    for rule in RULES:
        if not rule.applies(candidate):
            continue
        partners = sum(1 for card in owned if rule.partner(card))
        if partners:
            total += min(rule.cap, partners * rule.per_partner)
    return total


def explain(candidate: Card, owned: list[Card]) -> list[tuple[str, float, str]]:
    """Desglose de la sinergia, para el informe y para depurar una estrategia."""
    out = []
    for rule in RULES:
        if not rule.applies(candidate):
            continue
        partners = sum(1 for card in owned if rule.partner(card))
        if partners:
            out.append((rule.name, min(rule.cap, partners * rule.per_partner), rule.why))
    return sorted(out, key=lambda r: -r[1])
