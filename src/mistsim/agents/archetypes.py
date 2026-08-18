"""Los arquetipos de estrategia.

Ninguno se define por "los metales de mi personaje": cada uno se define por un MOTOR de
cartas, y el personaje es sólo un modificador. Por eso hay estrategias que cruzan varias
parejas de metales y otras que ignoran por completo el metal insignia.
"""
from __future__ import annotations

from mistsim.agents.profile import StrategyProfile
from mistsim.agents.tags import Tag
from mistsim.domain.metals import Metal as M

ARCHETYPES: dict[str, StrategyProfile] = {}


def _add(profile: StrategyProfile) -> StrategyProfile:
    ARCHETYPES[profile.name] = profile
    return profile


_add(StrategyProfile(
    name="rush-mision",
    description="Corre por las tres pistas de Misión y gana antes de que nadie te mate. "
                "Estaño, Latón y Bronce, con efectos que escalan según tu posición.",
    weights={"mission": 2.2, "combat": 0.4, "coin": 1.0},
    metal_affinity={M.TIN: 1.5, M.BRASS: 1.4, M.BRONZE: 1.3},
    tag_affinity={Tag.MISSION: 1.3, Tag.TRACK_AWARE: 1.4},
    mission_focus=0.95, cost_bias=-0.1,
))

_add(StrategyProfile(
    name="aggro-combate",
    description="Mata jugadores. Peltre y Acero, daño alto y curva agresiva, "
                "sin gastar nada en Misiones.",
    weights={"combat": 2.3, "mission": 0.3, "heal": 0.8},
    metal_affinity={M.PEWTER: 1.5, M.STEEL: 1.4, M.IRON: 1.2},
    tag_affinity={Tag.COMBAT: 1.3, Tag.REMOVAL: 1.5},
    mission_focus=0.05, cost_bias=0.15, panic_health=8,
))

_add(StrategyProfile(
    name="muro-defender",
    description="Peltre y Cobre: llena la mesa de Defenders, hazte intocable y gana "
                "por desgaste mientras los rivales se rompen los dientes.",
    weights={"heal": 2.0, "combat": 1.1, "mission": 0.9},
    metal_affinity={M.PEWTER: 1.4, M.COPPER: 1.5},
    tag_affinity={Tag.DEFENDER: 1.9, Tag.ALLY: 1.3, Tag.HEAL: 1.4},
    mission_focus=0.45, panic_health=20,
))

_add(StrategyProfile(
    name="motor-riot",
    description="Zinc: acumula Aliados y actívalos con Riot sin gastar quemas. "
                "Cada Aliado nuevo multiplica el valor de cada fuente de Riot.",
    weights={"coin": 1.4, "combat": 1.1, "mission": 1.1},
    metal_affinity={M.ZINC: 1.7, M.BRASS: 1.1},
    tag_affinity={Tag.ALLY: 1.7, Tag.ENABLER: 1.6},
    synergy_weight=2.0, mission_focus=0.5,
))

_add(StrategyProfile(
    name="tempo-seek",
    description="Bronce: usa las cartas caras del Mercado con Seek sin comprarlas nunca. "
                "Mazo delgadísimo y el Mercado como mano extendida.",
    weights={"mission": 1.4, "coin": 1.2, "combat": 1.0},
    metal_affinity={M.BRONZE: 1.8, M.COPPER: 1.1},
    tag_affinity={Tag.ENABLER: 1.8, Tag.MARKET_CONTROL: 1.4},
    synergy_weight=1.4, cost_bias=-0.25, mission_focus=0.7,
))

_add(StrategyProfile(
    name="adelgazar",
    description="Latón: elimina tus propias cartas de salida con Soothe hasta que cada "
                "robo saque sólo cartas buenas. Lento al principio, imparable al final.",
    weights={"coin": 1.3, "mission": 1.3, "draw": 1.6},
    metal_affinity={M.BRASS: 1.7, M.ZINC: 1.2},
    tag_affinity={Tag.THINNER: 2.0, Tag.DRAW: 1.4},
    synergy_weight=1.5, cost_bias=0.2, mission_focus=0.6,
))

_add(StrategyProfile(
    name="recursion-hierro",
    description="Hierro y Acero: Pull para apilar tus mejores cartas en el tope del mazo "
                "y Push para vaciar el Mercado de lo que le sirve al rival.",
    weights={"combat": 1.5, "draw": 1.7, "coin": 1.1},
    metal_affinity={M.IRON: 1.6, M.STEEL: 1.5},
    tag_affinity={Tag.RECURSION: 1.8, Tag.MARKET_CONTROL: 1.3},
    synergy_weight=1.6, cost_bias=0.3, mission_focus=0.35,
))

_add(StrategyProfile(
    name="combo-atium",
    description="Vía de victoria alternativa: acumula Atium y gana con Confrontation "
                "sin tocar Misiones ni matar a nadie. Frágil pero fulminante.",
    weights={"coin": 1.6, "combat": 0.7, "mission": 0.7},
    metal_affinity={M.ATIUM: 2.2, M.ZINC: 1.2, M.STEEL: 1.1},
    tag_affinity={Tag.ATIUM: 2.2, Tag.ECONOMY: 1.3},
    synergy_weight=2.2, cost_bias=0.5, mission_focus=0.3,
))

_add(StrategyProfile(
    name="rampa-economica",
    description="Zinc y Acero: monedas primero, cartas gordas después. Sacrifica los "
                "primeros turnos para dominar los últimos.",
    weights={"coin": 2.0, "combat": 0.9, "mission": 0.9},
    metal_affinity={M.ZINC: 1.5, M.STEEL: 1.3, M.TIN: 1.2},
    tag_affinity={Tag.ECONOMY: 1.6},
    cost_bias=0.45, mission_focus=0.5,
))

_add(StrategyProfile(
    name="motor-robo",
    description="Crewleader y las cadenas de robo: juega media baraja cada turno. "
                "Cuanto más robas, más metales activas y más se dispara todo.",
    weights={"draw": 2.2, "coin": 1.2, "combat": 1.0, "mission": 1.0},
    metal_affinity={M.IRON: 1.3, M.TIN: 1.3, M.ZINC: 1.2},
    tag_affinity={Tag.DRAW: 1.9, Tag.ALLY: 1.2},
    synergy_weight=1.7, mission_focus=0.5,
))

_add(StrategyProfile(
    name="equilibrado",
    description="Sin sesgos: compra lo que mejor puntúe. Es la referencia contra la que "
                "se mide si un arquetipo aporta algo de verdad.",
    weights={}, metal_affinity={}, tag_affinity={},
))


def get(name: str) -> StrategyProfile:
    if name not in ARCHETYPES:
        raise KeyError(f"arquetipo desconocido: {name!r}. Disponibles: {sorted(ARCHETYPES)}")
    return ARCHETYPES[name]


def names() -> list[str]:
    return sorted(ARCHETYPES)
