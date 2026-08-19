"""El bucle evolutivo: selección por torneo, cruce uniforme, mutación gaussiana, elitismo.

Sin dependencias externas (el proyecto no trae numpy): los genomas son `list[float]`
normales y las operaciones, bucles de Python. Con 34 genes y poblaciones de decenas de
individuos el coste de esto es irrelevante frente al de jugar las partidas del fitness.

## Selección sobre fitness ruidoso: por qué se reevalúa toda la generación

`fitness_fn` recibe `(vector, generation)`, no sólo `vector`: cada partida del gauntlet
es una muestra finita, así que su resultado trae error de muestreo (ver
`mistsim.optimize.fitness.standard_error`). Si se reutilizara el fitness ya calculado de
un individuo (p.ej. los que pasan por elitismo) generación tras generación, ese
individuo estaría compitiendo con una muestra vieja mientras el resto de la población
compite con una nueva -- la comparación dejaría de ser justa. Por eso este módulo
reevalúa la población ENTERA en cada generación: quien la llama debe variar la semilla
según `generation` (números aleatorios comunes dentro de la generación, distintos entre
generaciones) para que ningún individuo pueda sobreajustar un único conjunto fijo de
partidas durante toda la evolución.

Aun así, el máximo de una generación sigue sesgado al alza por la propia selección (el
"mejor" de la muestra es en parte el más afortunado). Por eso `run` acepta también
`validate_fn(vector) -> float`: una remedición del campeón de cada generación sobre una
muestra FIJA que nunca participa en la selección. Esa es la curva de convergencia que
hay que reportar, no `best_fitness` de entrenamiento -- y es también lo que decide cuál
es el mejor individuo de toda la corrida (`GAResult.best`), para no heredar el sesgo de
"el más afortunado en algún momento de N generaciones" hacia el resultado final.
"""
from __future__ import annotations

import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mistsim.agents import archetypes
from mistsim.optimize.genome import clamp_vector, profile_to_vector

Vector = list[float]
FitnessFn = Callable[[Vector, int], float]
ValidateFn = Callable[[Vector], float]


@dataclass
class Individual:
    vector: Vector
    fitness: float | None = None


@dataclass
class GenerationStats:
    generation: int
    best_fitness: float
    mean_fitness: float
    worst_fitness: float
    best_vector: Vector
    #: Remedición del campeón de esta generación sobre la muestra fija de validación,
    #: fuera de la presión de selección. `None` si no se pasó `validate_fn` a `run`.
    #: Es lo que hay que graficar como curva de convergencia, no `best_fitness`.
    validation_fitness: float | None = None


@dataclass
class GAResult:
    best: Individual
    history: list[GenerationStats] = field(default_factory=list)


def seed_population(size: int, rng: random.Random) -> list[Vector]:
    """Población inicial: los 11 arquetipos existentes, no ruido aleatorio (decisión
    congelada, ver README). Ya son puntos razonables del espacio de pesos; el GA parte
    de ahí en vez de perder generaciones redescubriéndolos.

    Si `size` es menor que 11 se toma un subconjunto (los primeros, en el orden estable
    de `archetypes.names()`, que está ordenado alfabéticamente). Si es mayor, el resto
    se rellena con mutaciones de los propios arquetipos — perturbaciones de puntos ya
    razonables, no ruido puro — repartidas cíclicamente entre los 11.
    """
    seeds = [profile_to_vector(archetypes.get(name)) for name in archetypes.names()]
    if size <= len(seeds):
        return [list(v) for v in seeds[:size]]

    population = [list(v) for v in seeds]
    i = 0
    while len(population) < size:
        base = seeds[i % len(seeds)]
        population.append(clamp_vector(_mutate(base, rate=0.3, scale=0.25, rng=rng)))
        i += 1
    return population


def _mutate(vector: Sequence[float], rate: float, scale: float, rng: random.Random) -> Vector:
    """Mutación gaussiana gen a gen: cada componente muta con probabilidad `rate`,
    desplazándose `N(0, scale)`. El resto queda intacto — no es un vector nuevo del
    todo, es una variación local del padre."""
    return [v + rng.gauss(0.0, scale) if rng.random() < rate else v for v in vector]


def _crossover(a: Sequence[float], b: Sequence[float], rng: random.Random) -> Vector:
    """Cruce uniforme: cada gen viene de un padre o del otro con la misma probabilidad."""
    return [a[i] if rng.random() < 0.5 else b[i] for i in range(len(a))]


def _tournament(ranked: list[Individual], k: int, rng: random.Random) -> Individual:
    """Selección por torneo: `k` individuos al azar, gana el de mejor fitness. Sobre una
    lista ya evaluada, así que no repite trabajo."""
    contenders = rng.sample(ranked, min(k, len(ranked)))
    return max(contenders, key=lambda ind: ind.fitness)


def run(
    fitness_fn: FitnessFn,
    *,
    population_size: int = 40,
    generations: int = 20,
    elite: int = 2,
    mutation_rate: float = 0.15,
    mutation_scale: float = 0.2,
    tournament_k: int = 3,
    seed: int = 0,
    validate_fn: ValidateFn | None = None,
    on_generation: Callable[[GenerationStats], None] | None = None,
) -> GAResult:
    """Evoluciona `population_size` individuos durante `generations` generaciones.

    `fitness_fn(vector, generation)` es la señal de SELECCIÓN: quien orquesta decide
    qué semilla usar para cada `generation` (ver `mistsim.optimize.fitness.
    training_seed`) para que la comparación dentro de una generación sea justa (números
    aleatorios comunes) sin que el GA pueda memorizar un único conjunto de partidas
    durante toda la corrida. La población entera se reevalúa cada generación -- ver el
    docstring del módulo para por qué eso es necesario y no sólo un despilfarro.

    `validate_fn(vector)`, si se da, remide al campeón de cada generación sobre una
    muestra fija ajena a la selección: alimenta `GenerationStats.validation_fitness`
    (la curva de convergencia real) y decide `GAResult.best` en vez de `best_fitness`
    de entrenamiento, que está sesgado al alza por construcción. Sin `validate_fn`,
    ambas cosas caen de vuelta al fitness de entrenamiento (útil para tests con una
    fitness sintética y barata que no necesita ese cuidado).

    El elitismo (los `elite` mejores de cada generación, por fitness de ENTRENAMIENTO,
    pasan a la siguiente) es sobre la selección, no sobre el reporte: sigue siendo la
    forma correcta de no perder progreso de una generación a la siguiente.
    """
    if elite < 0 or elite > population_size:
        raise ValueError("elite debe estar entre 0 y population_size")

    rng = random.Random(seed)
    population = [Individual(v) for v in seed_population(population_size, rng)]
    history: list[GenerationStats] = []
    best: Individual | None = None
    best_score = float("-inf")

    for gen in range(generations):
        # Reevaluar SIEMPRE la población entera, elites incluidos: cada generación usa
        # su propia banda de semillas (ver docstring del módulo), así que un fitness
        # calculado en una generación anterior no es comparable con el de esta.
        for ind in population:
            ind.fitness = fitness_fn(ind.vector, gen)

        ranked = sorted(population, key=lambda ind: ind.fitness, reverse=True)
        fits = [ind.fitness for ind in ranked]
        validation_fitness = validate_fn(ranked[0].vector) if validate_fn is not None else None
        stats = GenerationStats(
            generation=gen, best_fitness=ranked[0].fitness,
            mean_fitness=statistics.fmean(fits), worst_fitness=ranked[-1].fitness,
            best_vector=list(ranked[0].vector), validation_fitness=validation_fitness,
        )
        history.append(stats)

        # El "mejor de toda la corrida" se decide con la métrica que no está sesgada
        # por la selección: validación si la hay, entrenamiento si no.
        score = validation_fitness if validation_fitness is not None else ranked[0].fitness
        if score > best_score:
            best_score = score
            best = Individual(list(ranked[0].vector), score)

        if on_generation is not None:
            on_generation(stats)

        if gen == generations - 1:
            break

        next_gen = [Individual(list(ind.vector)) for ind in ranked[:elite]]
        while len(next_gen) < population_size:
            parent_a = _tournament(ranked, tournament_k, rng)
            parent_b = _tournament(ranked, tournament_k, rng)
            child = _crossover(parent_a.vector, parent_b.vector, rng)
            child = _mutate(child, mutation_rate, mutation_scale, rng)
            next_gen.append(Individual(clamp_vector(child)))
        population = next_gen

    assert best is not None  # generations >= 1 siempre deja al menos una evaluación
    return GAResult(best=best, history=history)
