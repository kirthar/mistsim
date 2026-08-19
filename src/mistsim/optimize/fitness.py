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

## Ruido de muestreo y las tres bandas de semillas

`evaluate_profile` juega un número FINITO de partidas por candidato, así que su
resultado es una estimación con error estándar, no el winrate real:

    SE = sqrt(0.25 / n)          # peor caso, p=0.5, n = games_per_matchup x 11 x 2

Con `games_per_matchup=3` (n=66) eso es ~6.2 puntos; con el valor por defecto
`games_per_matchup=4` (n=88), ~5.3 puntos. `standard_error()` calcula esto para
cualquier `n`. Seleccionar el máximo de una población sobre una medida con ese ruido
sesga al alza: el "mejor" de una generación es en parte el más afortunado, no el mejor
de verdad, y ese sesgo desaparece al re-medirlo con una muestra nueva ("regresión a la
media"). Por eso hay tres bandas de semillas, deliberadamente separadas y nunca
solapadas entre sí (`training_seed`, `validation_seed`, `final_eval_seed`):

- **Entrenamiento** — una por generación. Fija DENTRO de la generación (números
  aleatorios comunes: los individuos de una misma generación compiten sobre las mismas
  partidas, así que la comparación entre ellos es justa) pero distinta ENTRE
  generaciones, para que el GA no pueda sobreajustar un único conjunto fijo de partidas
  durante toda la evolución.
- **Validación** — fija en TODA la corrida, nunca usada para seleccionar individuos.
  Sirve para re-medir al mejor de cada generación con una muestra que no ha visto la
  presión de selección: es la curva de convergencia que se reporta, no el fitness de
  entrenamiento (que está sesgado al alza por construcción).
- **Evaluación final** — un tercer bloque, jamás tocado ni por entrenamiento ni por
  validación. Es el número que se reporta como resultado del perfil ganador.
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

# --- las tres bandas de semillas, ver docstring del módulo ---------------------------

#: Semillas que usa una sola generación: como mucho `len(GAUNTLET) * 2 * games_per_
#: matchup`. Con el gauntlet actual (11 x 2 = 22 emparejamientos, cada uno con hasta
#: 10 000 semillas propias, ver `evaluate_profile`) eso es <= 220 000; 1 000 000 de
#: separación entre generaciones deja margen de sobra y soporta miles de generaciones
#: sin que dos generaciones lleguen a compartir una sola partida.
GENERATION_SEED_STRIDE = 1_000_000

#: Bloque reservado para la curva de convergencia (validación): el mismo en todas las
#: generaciones -- lo que varía es el candidato que se mide, no la muestra -- y muy por
#: encima de cualquier offset que alcance el entrenamiento en una corrida razonable.
VALIDATION_SEED_OFFSET = 2_000_000_000

#: Bloque reservado para la medición final. Un tercer rango, tan alejado de los otros
#: dos como el de validación lo está del entrenamiento.
FINAL_EVAL_SEED_OFFSET = 4_000_000_000


def training_seed(base_seed: int, generation: int) -> int:
    """Semilla para evaluar la población durante `generation`-ésima generación.

    Todos los individuos de esa generación se miden con esta misma semilla base (más el
    offset por rival/asiento que ya aplica `evaluate_profile`): es números aleatorios
    comunes, la forma correcta de comparar candidatos entre sí sin que el ruido de
    muestreo decida el ganador. Generaciones distintas usan bloques distintos para que
    el GA no pueda memorizar un único conjunto de partidas durante toda la evolución.
    """
    return base_seed + generation * GENERATION_SEED_STRIDE


def validation_seed(base_seed: int) -> int:
    """Semilla fija para re-medir al mejor de cada generación fuera de la muestra que
    se usó para seleccionarlo. Nunca cambia entre generaciones: es lo que hace
    comparable la curva de convergencia consigo misma."""
    return base_seed + VALIDATION_SEED_OFFSET


def final_eval_seed(base_seed: int) -> int:
    """Semilla para la medición final del perfil ganador. Un tercer bloque, distinto
    del de entrenamiento y del de validación: el número que se reporta no puede venir
    de una muestra que ya influyó, ni directa ni indirectamente, en la búsqueda."""
    return base_seed + FINAL_EVAL_SEED_OFFSET


def standard_error(games: int) -> float:
    """Error estándar de un winrate medido sobre `games` partidas, en el peor caso
    (p=0.5, donde la varianza de una proporción es máxima).

    Sirve de regla rápida para no leer ruido de muestreo como una mejora: dos
    proporciones independientes con este error estándar sólo se distinguen con
    confianza si su diferencia supera unas ~2 veces esto (por ejemplo, con
    `games_per_matchup=3` -- 66 partidas por individuo -- el error estándar es ~6.2
    puntos, así que una diferencia de fitness por debajo de ~12 puntos no es fiable).
    """
    if games <= 0:
        return float("nan")
    return (0.25 / games) ** 0.5


def games_per_individual(games_per_matchup: int, gauntlet: tuple[str, ...] = GAUNTLET) -> int:
    """Cuántas partidas juega `evaluate_profile` por candidato: gauntlet x 2 asientos
    x `games_per_matchup`. Es el `n` que entra en `standard_error`."""
    return len(gauntlet) * 2 * games_per_matchup


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

    Esta función es agnóstica de FASE (entrenamiento/validación/evaluación final): sólo
    sabe jugar el gauntlet con el `base_seed` que le pasen. Es quien la llama (`ga.run`
    vía `cli/commands/optimize.py`) quien decide qué banda de semillas corresponde a
    cada llamada usando `training_seed`/`validation_seed`/`final_eval_seed` — ver el
    docstring del módulo.
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
