"""El bucle evolutivo: selección por torneo, cruce uniforme, mutación gaussiana, elitismo.

Sin dependencias externas (el proyecto no trae numpy): los genomas son `list[float]`
normales y las operaciones, bucles de Python. Con 34 genes y poblaciones de decenas de
individuos el coste de esto es irrelevante frente al de jugar las partidas del fitness.
"""
from __future__ import annotations

import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mistsim.agents import archetypes
from mistsim.optimize.genome import clamp_vector, profile_to_vector

Vector = list[float]
FitnessFn = Callable[[Vector], float]


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
    on_generation: Callable[[GenerationStats], None] | None = None,
) -> GAResult:
    """Evoluciona `population_size` individuos durante `generations` generaciones.

    `fitness_fn` recibe un genoma (`list[float]`) y devuelve un `float` a maximizar —
    quien orquesta decide qué significa (aquí, `FitnessResult.winrate`). `on_generation`
    se llama al cerrar cada generación, para poder imprimir el progreso sin que este
    módulo sepa nada de CLI ni de I/O.

    El elitismo (los `elite` mejores pasan intactos) garantiza que `best_fitness` nunca
    empeora de una generación a la siguiente: es la propiedad que explota el test de
    "el optimizador mejora sobre su población inicial".
    """
    if elite < 0 or elite > population_size:
        raise ValueError("elite debe estar entre 0 y population_size")

    rng = random.Random(seed)
    population = [Individual(v) for v in seed_population(population_size, rng)]
    history: list[GenerationStats] = []
    best: Individual | None = None

    for gen in range(generations):
        for ind in population:
            if ind.fitness is None:
                ind.fitness = fitness_fn(ind.vector)

        ranked = sorted(population, key=lambda ind: ind.fitness, reverse=True)
        fits = [ind.fitness for ind in ranked]
        stats = GenerationStats(
            generation=gen, best_fitness=ranked[0].fitness,
            mean_fitness=statistics.fmean(fits), worst_fitness=ranked[-1].fitness,
            best_vector=list(ranked[0].vector),
        )
        history.append(stats)
        if best is None or ranked[0].fitness > best.fitness:
            best = Individual(list(ranked[0].vector), ranked[0].fitness)
        if on_generation is not None:
            on_generation(stats)

        if gen == generations - 1:
            break

        next_gen = [Individual(list(ind.vector), ind.fitness) for ind in ranked[:elite]]
        while len(next_gen) < population_size:
            parent_a = _tournament(ranked, tournament_k, rng)
            parent_b = _tournament(ranked, tournament_k, rng)
            child = _crossover(parent_a.vector, parent_b.vector, rng)
            child = _mutate(child, mutation_rate, mutation_scale, rng)
            next_gen.append(Individual(clamp_vector(child)))
        population = next_gen

    assert best is not None  # generations >= 1 siempre deja al menos una evaluación
    return GAResult(best=best, history=history)
