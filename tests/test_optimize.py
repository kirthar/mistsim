"""Tests del optimizador de mazos: genoma, fitness y el bucle genético.

No usan `content` de sesión completa en los tests de fitness/GA salvo cuando hace falta
jugar partidas de verdad: son deliberadamente pequeños (pocos individuos, pocas
generaciones, `workers=1`) para no convertir la suite en una corrida de optimización.
"""
from __future__ import annotations

import random

import pytest

from mistsim.agents import archetypes
from mistsim.agents.profile import StrategyProfile
from mistsim.io import serial
from mistsim.optimize import ga
from mistsim.optimize.fitness import GAUNTLET, evaluate_profile
from mistsim.optimize.genome import (
    BOUNDS,
    DIMS,
    METAL_KEYS,
    SCALAR_KEYS,
    TAG_KEYS,
    WEIGHT_KEYS,
    clamp_vector,
    profile_to_vector,
    vector_to_profile,
)

# --- genoma: perfil <-> vector -------------------------------------------------------


def test_genome_dims_matches_profile_shape():
    """34 = 5 weights + 9 metal_affinity + 16 tag_affinity + 4 escalares."""
    assert DIMS == 34
    assert len(WEIGHT_KEYS) == 5
    assert len(METAL_KEYS) == 9
    assert len(TAG_KEYS) == 16
    assert len(SCALAR_KEYS) == 4
    assert len(BOUNDS) == DIMS


def test_vector_roundtrips_through_profile():
    """vector -> perfil -> vector debe devolver exactamente el mismo vector.

    panic_health se redondea a entero dentro de StrategyProfile, así que se construye
    el vector de prueba con un valor ya entero para que el roundtrip sea exacto en las
    34 posiciones, no sólo aproximado.
    """
    rng = random.Random(1234)
    vector = [rng.uniform(0.2, 2.5) for _ in range(DIMS)]
    vector[-1] = 15.0  # panic_health, para que round() no lo mueva

    profile = vector_to_profile(vector, name="test-roundtrip")
    back = profile_to_vector(profile)

    assert back == pytest.approx(vector)


def test_profile_roundtrips_through_vector_for_every_archetype():
    """Los 11 arquetipos deben sobrevivir el viaje perfil -> vector -> perfil: mismo
    comportamiento aunque el perfil reconstruido traiga los dicts completos en vez de
    sólo las claves que el arquetipo original se molestó en escribir."""
    for name in archetypes.names():
        original = archetypes.get(name)
        vector = profile_to_vector(original)
        assert len(vector) == DIMS

        rebuilt = vector_to_profile(vector, name=name, description=original.description)

        assert rebuilt.synergy_weight == pytest.approx(original.synergy_weight)
        assert rebuilt.cost_bias == pytest.approx(original.cost_bias)
        assert rebuilt.mission_focus == pytest.approx(original.mission_focus)
        assert rebuilt.panic_health == original.panic_health
        for key in WEIGHT_KEYS:
            assert rebuilt.weights[key] == pytest.approx(original.weights.get(key, 1.0))
        for metal in METAL_KEYS:
            assert rebuilt.metal_affinity[metal] == pytest.approx(
                original.metal_affinity.get(metal, 1.0))
        for tag in TAG_KEYS:
            assert rebuilt.tag_affinity[tag] == pytest.approx(
                original.tag_affinity.get(tag, 1.0))


def test_profile_roundtrips_through_serial_json():
    """El perfil que produce el vector debe sobrevivir también el otro contrato
    congelado: `io.serial`, que es cómo se guarda y se recarga como JSON."""
    vector = profile_to_vector(archetypes.get("aggro-combate"))
    profile = vector_to_profile(vector, name="candidato-json", description="d")

    data = serial.profile_to_dict(profile)
    back = serial.profile_from_dict(data)

    assert profile_to_vector(back) == pytest.approx(profile_to_vector(profile))


def test_vector_to_profile_rejects_wrong_length():
    with pytest.raises(ValueError):
        vector_to_profile([1.0] * (DIMS - 1), name="corto")


def test_clamp_vector_respects_bounds():
    huge = [1e6] * DIMS
    tiny = [-1e6] * DIMS
    clamped_hi = clamp_vector(huge)
    clamped_lo = clamp_vector(tiny)
    for value, (_lo, hi) in zip(clamped_hi, BOUNDS, strict=True):
        assert value == pytest.approx(hi)
    for value, (lo, _hi) in zip(clamped_lo, BOUNDS, strict=True):
        assert value == pytest.approx(lo)


# --- fitness: gauntlet fijo, determinista --------------------------------------------


def test_gauntlet_is_the_eleven_archetypes():
    """Decisión congelada: el fitness usa siempre los 11 arquetipos, nunca autojuego."""
    assert set(GAUNTLET) == set(archetypes.names())
    assert len(GAUNTLET) == 11


def test_fitness_is_deterministic_for_the_same_seed():
    profile = archetypes.get("equilibrado").clone(name="__candidato__")
    kwargs = dict(games_per_matchup=1, workers=1, base_seed=7, character="vin", max_turns=20)

    first = evaluate_profile(profile, **kwargs)
    second = evaluate_profile(profile, **kwargs)

    assert first == second


def test_fitness_matches_between_one_and_two_workers():
    """La misma garantía de `run_batch` (1 worker == varios workers) debe sobrevivir a
    envolverlo en `evaluate_profile`, o el fitness de una corrida en serie no sería
    comparable con el de una en paralelo."""
    profile = archetypes.get("rush-mision").clone(name="__candidato__")
    single = evaluate_profile(profile, games_per_matchup=1, workers=1, base_seed=3,
                              character="vin", max_turns=20)
    parallel = evaluate_profile(profile, games_per_matchup=1, workers=2, base_seed=3,
                                character="vin", max_turns=20)
    assert single == parallel


def test_fitness_breakdown_accounts_mission_wins_separately():
    """`wins_sin_mision` nunca puede superar `wins`: es un subconjunto de las mismas
    victorias, con las de Misión descontadas."""
    profile = archetypes.get("rush-mision").clone(name="__candidato__")
    result = evaluate_profile(profile, games_per_matchup=2, workers=1, base_seed=11,
                              character="vin", max_turns=25)
    assert result.games == len(GAUNTLET) * 2 * 2
    assert result.wins_sin_mision <= result.wins
    assert result.wins_sin_mision + result.mission_wins == result.wins
    assert 0.0 <= result.winrate <= 1.0
    assert 0.0 <= result.winrate_sin_mision <= result.winrate + 1e-9


def test_fitness_rejects_unknown_character():
    profile = archetypes.get("equilibrado").clone(name="__candidato__")
    with pytest.raises(KeyError):
        evaluate_profile(profile, games_per_matchup=1, workers=1, character="no-existe")


# --- el bucle genético -----------------------------------------------------------------


def test_seed_population_starts_from_the_eleven_archetypes():
    """Decisión congelada: población inicial = los 11 arquetipos, no ruido aleatorio."""
    rng = random.Random(0)
    population = ga.seed_population(11, rng)
    seed_vectors = {tuple(profile_to_vector(archetypes.get(n))) for n in archetypes.names()}
    assert {tuple(v) for v in population} == seed_vectors


def test_seed_population_smaller_than_eleven_is_a_subset():
    rng = random.Random(0)
    population = ga.seed_population(4, rng)
    seed_vectors = {tuple(profile_to_vector(archetypes.get(n))) for n in archetypes.names()}
    assert len(population) == 4
    assert all(tuple(v) in seed_vectors for v in population)


def test_seed_population_larger_than_eleven_keeps_all_archetypes_and_fills_rest():
    rng = random.Random(0)
    population = ga.seed_population(15, rng)
    seed_vectors = {tuple(profile_to_vector(archetypes.get(n))) for n in archetypes.names()}
    assert len(population) == 15
    present = {tuple(v) for v in population}
    assert seed_vectors <= present
    for vector in population:
        for value, (lo, hi) in zip(vector, BOUNDS, strict=True):
            assert lo <= value <= hi


def test_ga_run_with_synthetic_fitness_converges_towards_the_optimum():
    """El bucle evolutivo en sí, con una fitness sintética y barata (sin jugar
    partidas): comprueba selección/cruce/mutación/elitismo con una señal limpia."""
    target = [2.0] * DIMS

    def fitness_fn(vector: list[float]) -> float:
        return -sum((a - b) ** 2 for a, b in zip(vector, target, strict=True))

    result = ga.run(fitness_fn, population_size=12, generations=15, elite=2,
                    mutation_rate=0.2, mutation_scale=0.3, seed=0)

    assert result.history[-1].best_fitness >= result.history[0].best_fitness
    assert result.history[-1].best_fitness > result.history[len(result.history) // 2].best_fitness


def test_ga_elitism_never_regresses_best_fitness():
    """Con elitismo, `best_fitness` no puede empeorar nunca de una generación a la
    siguiente -- es la propiedad que hace fiable "el optimizador mejora"."""
    rng = random.Random(5)

    def noisy_fitness(vector: list[float]) -> float:
        return sum(vector) + rng.uniform(-0.01, 0.01)

    result = ga.run(noisy_fitness, population_size=10, generations=10, elite=1, seed=2)
    bests = [g.best_fitness for g in result.history]
    assert bests == sorted(bests)


def test_optimizer_improves_over_its_initial_population_on_real_games():
    """Integración de punta a punta con partidas de verdad: genoma -> perfil ->
    `evaluate_profile` -> `run_batch` -> motor. Deliberadamente diminuto (población y
    generaciones mínimas, `workers=1`) para que siga siendo un test, no una corrida de
    optimización; la corrida de verdad se documenta en el informe del stream.
    """
    def fitness_fn(vector: list[float]) -> float:
        profile = vector_to_profile(vector, name="__candidato__")
        result = evaluate_profile(profile, games_per_matchup=1, workers=1, base_seed=99,
                                  character="vin", max_turns=20)
        return result.winrate

    result = ga.run(fitness_fn, population_size=4, generations=2, elite=1, seed=1)

    # El elitismo por sí solo ya garantiza esto (ver test_ga_elitism_never_regresses_
    # best_fitness); aquí se comprueba además que todo el cableado real -- vector,
    # perfil, gauntlet, run_batch, motor -- efectivamente produce números usables.
    assert result.history[-1].best_fitness >= result.history[0].best_fitness
    assert 0.0 <= result.best.fitness <= 1.0


def test_optimized_profile_is_playable_like_any_archetype(content):
    """El perfil que sale del GA debe poder jugar una partida completa igual que
    cualquier arquetipo -- es justo el requisito de "cargable y jugable"."""
    from mistsim.agents.utility import UtilityAgent
    from mistsim.domain.state import GameConfig
    from mistsim.engine.game import GameEngine

    vector = profile_to_vector(archetypes.get("equilibrado"))
    vector[0] = 1.8  # combat weight, para que no sea un clon exacto del arquetipo
    profile: StrategyProfile = vector_to_profile(vector, name="__candidato__")

    engine = GameEngine(content=content, config=GameConfig(num_players=2, max_turns=25), seed=3)
    result = engine.run([
        UtilityAgent(profile, seed=1),
        UtilityAgent(archetypes.get("equilibrado"), seed=2),
    ])

    assert result.reason
    assert result.players[0].strategy == "__candidato__"
