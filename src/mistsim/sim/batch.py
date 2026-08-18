"""Ejecución de lotes de partidas, en paralelo.

Contrato congelado en la Fase A. El optimizador genera aquí sus evaluaciones y la
minería de combos su corpus, así que la firma no cambia: sólo se le añaden campos.

Reproducibilidad: la semilla de cada partida se deriva de su ÍNDICE, no de un RNG
compartido. Con varios procesos un RNG compartido haría que el mismo lote diera
resultados distintos según el orden en que terminaran los workers.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Iterator
from dataclasses import dataclass, field

from mistsim.agents import archetypes
from mistsim.agents.profile import StrategyProfile
from mistsim.agents.utility import UtilityAgent
from mistsim.content.loader import Content, load_content
from mistsim.domain.state import GameConfig
from mistsim.engine.events import STATS_KINDS, EventLog
from mistsim.engine.game import GameEngine, GameResult


@dataclass(frozen=True)
class BatchSpec:
    """Qué partida jugar. Debe ser picklable: viaja a los procesos worker.

    Por eso las estrategias van como **nombres de arquetipo o perfiles**, nunca como
    agentes ya construidos, y el contenido no viaja: cada worker lo carga una vez.
    """

    strategies: tuple[str, ...]
    config: GameConfig = field(default_factory=GameConfig)
    characters: tuple[str, ...] | None = None
    base_seed: int = 0
    #: Perfiles a medida, por nombre. Permite evaluar candidatos del optimizador que
    #: todavía no están en el registro de arquetipos.
    custom_profiles: tuple[tuple[str, StrategyProfile], ...] = ()

    def profile(self, name: str) -> StrategyProfile:
        for custom_name, profile in self.custom_profiles:
            if custom_name == name:
                return profile
        return archetypes.get(name)

    def seed_for(self, index: int) -> int:
        return self.base_seed + index


#: Contenido cacheado por proceso: cargarlo cuesta y no cambia durante el lote.
_CONTENT: Content | None = None


def _content() -> Content:
    global _CONTENT
    if _CONTENT is None:
        _CONTENT = load_content()
    return _CONTENT


def play_one(spec: BatchSpec, index: int, collect_log: bool = True) -> GameResult:
    """Juega una partida del lote. Determinista para un `(spec, index)` dado."""
    seed = spec.seed_for(index)
    log = EventLog(keep=None if collect_log else STATS_KINDS)
    engine = GameEngine(content=_content(), config=spec.config, seed=seed, log=log)
    agents = [
        UtilityAgent(spec.profile(name), seed=seed + seat)
        for seat, name in enumerate(spec.strategies)
    ]
    characters = list(spec.characters) if spec.characters else None
    return engine.run(agents, characters=characters)


def _worker(args: tuple[BatchSpec, int, bool]) -> GameResult:
    spec, index, collect_log = args
    return play_one(spec, index, collect_log)


def run_batch(spec: BatchSpec, n: int, workers: int = 0,
              collect_log: bool = True) -> Iterator[GameResult]:
    """Juega `n` partidas y las va devolviendo según terminan.

    `workers=0` usa todos los núcleos; `workers=1` corre en este proceso, que es lo que
    quieres al depurar porque los fallos suben con su traza completa.

    Es un generador: un lote de 100 000 partidas nunca está entero en memoria, así que
    puede encadenarse directamente con `serial.write_corpus`.
    """
    if n <= 0:
        return
    if workers == 1:
        for index in range(n):
            yield play_one(spec, index, collect_log)
        return

    count = workers if workers > 0 else (os.cpu_count() or 1)
    count = max(1, min(count, n))
    payload = [(spec, index, collect_log) for index in range(n)]
    # 'spawn' no está garantizado en todas las plataformas con el mismo coste, pero
    # fork comparte el contenido ya cargado y es lo que hace rápido el arranque.
    # `imap` y no `imap_unordered`: el orden de salida es parte de la reproducibilidad.
    # Un mismo lote debe dar la misma secuencia con 1 worker y con 8, y el reparto
    # desigual que evita `imap_unordered` cuesta poco frente a eso.
    with mp.Pool(processes=count) as pool:
        yield from pool.imap(_worker, payload, chunksize=_chunk(n, count))


def _chunk(n: int, workers: int) -> int:
    """Trozos ni tan grandes que descompensen ni tan pequeños que dominen el envío."""
    return max(1, min(32, n // (workers * 4) or 1))
