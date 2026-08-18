"""Fitness: winrate del perfil candidato contra un gauntlet FIJO de arquetipos.

Decisión de diseño (congelada, ver README de este stream): el gauntlet son siempre los
11 arquetipos escritos a mano, nunca autojuego entre candidatos. Con autojuego el rival
cambia cada generación y el fitness de la generación 40 no es comparable con el de la 5
— no se sabría si el candidato mejoró o si simplemente le tocaron rivales más flojos.

Cada partida del gauntlet es un 1 contra 1 PvP: el candidato contra UN arquetipo, con
los asientos alternados para que el orden de turno no sesgue el resultado. Es la lectura
literal del presupuesto de cómputo acordado (11 rivales x N partidas x 2 asientos);
escalar a partidas de más jugadores o a Cooperativo queda fuera de esta entrega — ver
el informe del stream.
"""
from __future__ import annotations

from dataclasses import dataclass

from mistsim.agents import archetypes
from mistsim.agents.profile import StrategyProfile
from mistsim.content.loader import load_content
from mistsim.domain.state import GameConfig
from mistsim.sim.batch import BatchSpec, run_batch

#: Nombre reservado para el candidato dentro de un `BatchSpec.custom_profiles`. No debe
#: colisionar con ningún arquetipo real.
CANDIDATE_NAME = "__candidato__"

#: El gauntlet: los 11 arquetipos, fijo para que el fitness sea comparable entre
#: generaciones. `tuple(archetypes.names())` en vez de una lista a mano para que si se
#: añade o quita un arquetipo el gauntlet lo recoja solo.
GAUNTLET: tuple[str, ...] = tuple(archetypes.names())

#: Razón de victoria que emite el motor al completar las tres pistas de Misión. Los
#: datos de Misión son homebrew (ver README) y hoy explican el 84% de las partidas a 3
#: jugadores; separar esta razón permite reportar el fitness con y sin ella.
MISSION_WIN_REASON = "all-missions"

_CHARACTER_POOL: tuple[str, ...] | None = None


def _character_pool() -> tuple[str, ...]:
    """Personajes jugables, sin la variante promo (mismo criterio que `GameEngine`)."""
    global _CHARACTER_POOL
    if _CHARACTER_POOL is None:
        content = load_content()
        _CHARACTER_POOL = tuple(sorted(c.id for c in content.characters if not c.promo))
    return _CHARACTER_POOL


def _opponent_character(target: str, offset: int) -> str:
    """Personaje rival, rotando de forma determinista para no sobreajustar a un único
    enfrentamiento de personajes."""
    pool = [c for c in _character_pool() if c != target] or list(_character_pool())
    return pool[offset % len(pool)]


@dataclass(frozen=True)
class FitnessResult:
    """Resultado de evaluar un perfil contra el gauntlet completo.

    `winrate` es la métrica que usa el GA como fitness. `winrate_sin_mision` recalcula
    el numerador tratando una victoria por Misiones como no-victoria (el denominador de
    partidas es el mismo): mide cuánto del winrate depende del atajo de completar las
    tres pistas en vez de vencer en combate o por desgaste, que es justo el mecanismo
    inventado. Compararlas separa estrategia real de artefacto de los datos homebrew.
    """

    winrate: float
    winrate_sin_mision: float
    games: int
    wins: int
    wins_sin_mision: int
    mission_wins: int


def evaluate_profile(
    profile: StrategyProfile,
    *,
    games_per_matchup: int = 6,
    workers: int = 0,
    base_seed: int = 0,
    character: str | None = None,
    max_turns: int = 60,
    gauntlet: tuple[str, ...] = GAUNTLET,
) -> FitnessResult:
    """Juega al candidato contra cada rival del gauntlet, asientos alternados.

    Determinista para `(profile, character, base_seed, games_per_matchup, gauntlet)`
    dados: cada emparejamiento usa un tramo de semillas propio derivado de su índice, no
    de un contador compartido, así que el resultado no depende de `workers` ni del orden
    en que terminen los procesos — la misma garantía que ya da `run_batch`.
    """
    config = GameConfig(num_players=2, max_turns=max_turns)
    wins = 0
    wins_sin_mision = 0
    mission_wins = 0
    games = 0

    for rival_index, rival in enumerate(gauntlet):
        for seat in (0, 1):
            order = (CANDIDATE_NAME, rival) if seat == 0 else (rival, CANDIDATE_NAME)
            candidate_seat = seat

            characters = None
            if character is not None:
                opponent = _opponent_character(character, rival_index * 2 + seat)
                chars = [None, None]
                chars[candidate_seat] = character
                chars[1 - candidate_seat] = opponent
                characters = tuple(chars)

            # Un tramo de 10 000 semillas por (rival, asiento) evita que dos
            # emparejamientos se pisen la secuencia de semillas aunque el número de
            # partidas por emparejamiento cambie entre llamadas.
            spec = BatchSpec(
                strategies=order, config=config, characters=characters,
                base_seed=base_seed + (rival_index * 2 + seat) * 10_000,
                custom_profiles=((CANDIDATE_NAME, profile),),
            )
            for result in run_batch(spec, games_per_matchup, workers=workers,
                                    collect_log=False):
                games += 1
                if result.winner == candidate_seat:
                    wins += 1
                    if result.reason == MISSION_WIN_REASON:
                        mission_wins += 1
                    else:
                        wins_sin_mision += 1

    winrate = wins / games if games else 0.0
    winrate_sin_mision = wins_sin_mision / games if games else 0.0
    return FitnessResult(
        winrate=winrate, winrate_sin_mision=winrate_sin_mision, games=games,
        wins=wins, wins_sin_mision=wins_sin_mision, mission_wins=mission_wins,
    )
