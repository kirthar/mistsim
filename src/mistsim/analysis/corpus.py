"""Generación y lectura del corpus de partidas para la minería de combos.

El corpus se genera con `run_batch` y se persiste con `serial.write_corpus`, que es el
contrato congelado de la Fase A. Aquí sólo se decide **qué partidas** jugar y **cómo se
convierte cada asiento en una observación**.

Dos decisiones importantes:

1. `BatchSpec` fija las estrategias de todo el lote, así que un solo lote mediría un
   único emparejamiento. El plan reparte las N partidas entre muchos lotes con
   asignaciones distintas de arquetipo a asiento, en rotación determinista, para que
   todos los arquetipos aparezcan un número parecido de veces y en todos los asientos.
2. `collect_log=False`: el corpus baja de 562 a 58 eventos por partida y la minería no
   necesita nada más que `purchases` y `won`.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from mistsim.agents import archetypes
from mistsim.content.loader import Content, load_content
from mistsim.domain.state import GameConfig, Mode
from mistsim.io import serial
from mistsim.sim.batch import BatchSpec, run_batch

#: Separación entre las semillas base de dos lotes. Más grande que cualquier lote
#: razonable, para que dos lotes nunca compartan la semilla de una partida.
SEED_STRIDE = 1_000_003


@dataclass(frozen=True)
class CorpusSpec:
    """Qué corpus generar."""

    games: int = 5000
    #: Números de jugadores a mezclar. Cada uno acaba siendo un estrato propio.
    players: tuple[int, ...] = (2, 3, 4)
    mode: Mode = Mode.PVP
    max_turns: int = 60
    seed: int = 0
    #: Partidas por lote. Cuanto más pequeño, más variedad de emparejamientos; cuanto
    #: más grande, menos veces se paga el arranque del pool de procesos.
    games_per_batch: int = 25
    strategies: tuple[str, ...] = field(default_factory=lambda: tuple(archetypes.names()))


def plan_batches(spec: CorpusSpec) -> list[tuple[BatchSpec, int]]:
    """Reparte `spec.games` partidas en lotes con emparejamientos rotatorios.

    La rotación es determinista y coprima en la práctica con el número de arquetipos,
    así que cubre asientos y rivales sin necesidad de un RNG: el mismo `CorpusSpec` da
    siempre el mismo plan y por tanto el mismo corpus.
    """
    names = list(spec.strategies)
    if not names:
        raise ValueError("hace falta al menos un arquetipo")
    plan: list[tuple[BatchSpec, int]] = []
    remaining = spec.games
    index = 0
    cursor = 0
    while remaining > 0:
        players = spec.players[index % len(spec.players)]
        seats = tuple(names[(cursor + seat) % len(names)] for seat in range(players))
        cursor += players + 1  # +1 rompe la periodicidad cuando players divide a len(names)
        games = min(spec.games_per_batch, remaining)
        config = GameConfig(mode=spec.mode, num_players=players, max_turns=spec.max_turns)
        plan.append((BatchSpec(strategies=seats, config=config,
                               base_seed=spec.seed + index * SEED_STRIDE), games))
        remaining -= games
        index += 1
    return plan


def generate(path: str | Path, spec: CorpusSpec, workers: int = 0) -> int:
    """Juega el corpus y lo escribe como JSONL. Devuelve cuántas partidas escribió.

    Escribe lote a lote en modo append, así que una corrida de 100 000 partidas nunca
    tiene el corpus en memoria y se puede interrumpir sin perder lo ya jugado.
    """
    path = Path(path)
    total = 0
    for i, (batch, games) in enumerate(plan_batches(spec)):
        results = run_batch(batch, games, workers=workers, collect_log=False)
        total += serial.write_corpus(path, results, include_log=False, append=i > 0)
    return total


# --- observaciones -----------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """Un asiento de una partida: qué compró y si ganó.

    La unidad de análisis es el asiento, no la partida: la sinergia es una propiedad
    de un mazo concreto, y en una partida a 4 hay cuatro mazos distintos.
    """

    strategy: str
    players: int
    mode: str
    #: Cartas de Mercado distintas que llegó a tener. Conjunto, no lista: dos copias de
    #: la misma carta no son un par consigo misma.
    cards: frozenset[str]
    won: bool
    #: Índice de la partida dentro del corpus. Sirve para partirlo en dos mitades
    #: independientes SIN cortar por la mitad ninguna partida: los asientos de una
    #: misma partida comparten resultado y tienen que caer del mismo lado.
    game: int = -1

    @property
    def size(self) -> int:
        return len(self.cards)


def market_names(content: Content | None = None) -> frozenset[str]:
    """Las 65 cartas de Mercado.

    El universo se restringe a ellas a propósito: `purchases` también recoge las cartas
    recuperadas del montón de eliminadas por Soar, que pueden ser Entrenamientos o
    Financiaciones del mazo inicial. Todo el mundo empieza con ésas, así que como ítem
    de una regla de asociación no dicen nada.
    """
    return frozenset(card.name for card in (content or load_content()).market)


def card_costs(content: Content | None = None) -> dict[str, int]:
    return {card.name: card.cost for card in (content or load_content()).market}


#: Finales que sólo existen con Lord Ruler en mesa, o sea en Solo/Coop.
COOP_REASONS = frozenset({"lord-ruler-defeated", "lord-ruler-deck-empty",
                          "all-players-eliminated"})


def infer_mode(raw: dict) -> str:
    """Deduce el modo de una partida serializada.

    `result_to_dict` no guarda el modo (ver el informe: es un punto de coordinación,
    añadir `mode` a `GameResult` lo resolvería de raíz). Mientras tanto se deduce por
    dos señales que en PvP no pueden darse: un final que exige Lord Ruler, o más de un
    ganador —en Coop se gana en equipo y `won` es el mismo para todos los asientos—.
    """
    if raw.get("reason") in COOP_REASONS:
        return "coop"
    players = raw.get("players") or []
    if len(players) == 1 or sum(1 for p in players if p.get("won")) > 1:
        return "coop"
    return "pvp"


def read_observations(path: str | Path, *, universe: frozenset[str] | None = None,
                      min_cards: int = 0) -> Iterator[Observation]:
    """Convierte el corpus JSONL en observaciones, de forma perezosa.

    Por defecto **no** se descarta ningún asiento, ni siquiera el que no compró nada.
    Tienta filtrarlos, pero son controles legítimos: forman parte de la celda "no tiene
    ninguna de las dos" de todos los pares, y quitarlos sube esa tasa de victoria base
    y con ella el lift de todo el ranking a la vez. De separarlos ya se encarga la
    estratificación por tamaño de mazo.
    """
    if universe is None:
        universe = market_names()
    for game, raw in enumerate(serial.read_corpus_dicts(path)):
        players = len(raw["players"])
        mode = infer_mode(raw)
        for player in raw["players"]:
            cards = frozenset(universe.intersection(player["purchases"]))
            if len(cards) < min_cards:
                continue
            yield Observation(strategy=player["strategy"], players=players, mode=mode,
                              cards=cards, won=bool(player["won"]), game=game)
