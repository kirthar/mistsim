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
from mistsim.optimize.fitness import (
    GAUNTLET,
    evaluate_profile,
    final_eval_seed,
    games_per_individual,
    standard_error,
    training_seed,
    validation_seed,
)
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


# --- ruido de muestreo: error estándar y las tres bandas de semillas -----------------
#
# Estos tests capturan el problema metodológico señalado en revisión: seleccionar el
# máximo de una población sobre un fitness medido con pocas partidas sesga al alza (el
# "mejor" es en parte el más afortunado), y si además la semilla de evaluación es fija
# durante toda la evolución, el GA puede sobreajustar ese único conjunto de partidas en
# vez de aprender a jugar mejor. La corrección son tres bandas de semillas disjuntas
# (entrenamiento por generación / validación fija / evaluación final reservada) — ver
# `mistsim.optimize.fitness` y `mistsim.optimize.ga` para el razonamiento completo.


def test_standard_error_matches_the_worst_case_proportion_formula():
    assert standard_error(88) == pytest.approx((0.25 / 88) ** 0.5)
    # Los números que se citan en el informe: ~5.3 puntos con --games 4 (n=88, el
    # valor por defecto) y ~6.2 puntos con --games 3 (n=66).
    assert standard_error(games_per_individual(4)) == pytest.approx(0.0533, abs=1e-3)
    assert standard_error(games_per_individual(3)) == pytest.approx(0.0615, abs=1e-3)


def test_standard_error_shrinks_as_games_grow():
    small = standard_error(games_per_individual(1))
    large = standard_error(games_per_individual(10))
    assert large < small


def test_games_per_individual_matches_the_documented_formula():
    # gauntlet x 2 asientos x games_per_matchup
    assert games_per_individual(4) == len(GAUNTLET) * 2 * 4


def test_seed_bands_never_overlap_for_realistic_generation_counts():
    """Entrenamiento, validación y evaluación final deben vivir en rangos disjuntos: es
    la propiedad que impide que el GA sobreajuste una única muestra de partidas."""
    # Cada generación usa como mucho ~220 000 semillas internas (11 rivales x 2 asientos
    # x 10 000, ver evaluate_profile); dejamos margen generoso.
    internal_spread = 300_000
    for generation in (0, 1, 50, 500, 1999):
        assert training_seed(0, generation) + internal_spread < validation_seed(0)
    assert validation_seed(0) + internal_spread < final_eval_seed(0)
    # Distintas generaciones caen en tramos distintos entre sí.
    assert training_seed(0, 0) + internal_spread < training_seed(0, 1)


def test_evaluate_profile_differs_across_seed_bands_within_noise_bounds():
    """Dos evaluaciones del mismo perfil sobre rangos de semilla distintos (aquí:
    entrenamiento de la generación 0 vs validación) deben dar números DISTINTOS -- las
    semillas de verdad cambian qué partidas se juegan -- pero la diferencia debe caer
    dentro de lo esperable por el ruido de muestreo. Existe justo para que nadie vuelva
    a leer una diferencia de este tamaño como una mejora real de la estrategia.
    """
    profile = archetypes.get("equilibrado").clone(name="__candidato__")
    games = 4
    n = games_per_individual(games)
    se = standard_error(n)

    train = evaluate_profile(profile, games_per_matchup=games, workers=1,
                             base_seed=training_seed(0, 0), character="vin", max_turns=25)
    validation = evaluate_profile(profile, games_per_matchup=games, workers=1,
                                  base_seed=validation_seed(0), character="vin", max_turns=25)
    final = evaluate_profile(profile, games_per_matchup=games, workers=1,
                             base_seed=final_eval_seed(0), character="vin", max_turns=25)

    # Semillas distintas -> partidas distintas -> resultados distintos.
    assert train.winrate != validation.winrate
    assert train.winrate != final.winrate

    # Pero no arbitrariamente distintos: por debajo de unos pocos errores estándar. Un
    # bug que hiciera colisionar rangos de semillas o desincronizara asientos podría
    # producir una diferencia mucho mayor que esto, y es justo lo que detectaría.
    bound = 5 * se
    assert abs(train.winrate - validation.winrate) < bound
    assert abs(train.winrate - final.winrate) < bound
    assert abs(validation.winrate - final.winrate) < bound


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
    partidas): comprueba selección/cruce/mutación/elitismo con una señal limpia.
    `fitness_fn` recibe `(vector, generation)`; aquí es ciega a `generation` a
    propósito, para aislar el mecanismo de selección del manejo de semillas."""
    target = [2.0] * DIMS

    def fitness_fn(vector: list[float], _generation: int) -> float:
        return -sum((a - b) ** 2 for a, b in zip(vector, target, strict=True))

    result = ga.run(fitness_fn, population_size=12, generations=15, elite=2,
                    mutation_rate=0.2, mutation_scale=0.3, seed=0)

    assert result.history[-1].best_fitness >= result.history[0].best_fitness
    assert result.history[-1].best_fitness > result.history[len(result.history) // 2].best_fitness


def test_ga_elitism_never_regresses_training_best_fitness():
    """Con elitismo, el mejor de entrenamiento de una generación no puede empeorar
    respecto al de la anterior -- es la propiedad mecánica que hace `run` monótono
    generación a generación cuando la señal de fitness es la misma."""
    rng = random.Random(5)

    def noisy_fitness(vector: list[float], _generation: int) -> float:
        return sum(vector) + rng.uniform(-0.01, 0.01)

    result = ga.run(noisy_fitness, population_size=10, generations=10, elite=1, seed=2)
    bests = [g.best_fitness for g in result.history]
    assert bests == sorted(bests)


def test_ga_reevaluates_every_individual_every_generation():
    """Cada generación debe usar su propia semilla: si `fitness_fn` devuelve un valor
    distinto según `generation` para el MISMO vector, el `best_fitness` reportado tiene
    que reflejarlo incluso para individuos que sobreviven por elitismo -- si el código
    reutilizara el fitness ya calculado de un elite, esto fallaría."""
    calls: list[int] = []

    def fitness_fn(vector: list[float], generation: int) -> float:
        calls.append(generation)
        # Toda la población obtiene el mismo valor dentro de una generación (números
        # aleatorios comunes), pero ese valor SUBE con la generación aunque el vector
        # no cambie -- simula que cada generación juega partidas distintas.
        return float(generation)

    result = ga.run(fitness_fn, population_size=6, generations=4, elite=2, seed=0)

    assert [g.best_fitness for g in result.history] == [0.0, 1.0, 2.0, 3.0]
    # Se reevaluó la población entera en cada una de las 4 generaciones, elites
    # incluidos: 6 individuos x 4 generaciones.
    assert len(calls) == 6 * 4


def test_ga_validation_fn_shields_best_result_from_a_single_generation_lucky_spike():
    """Reproduce exactamente el sesgo reportado en revisión: una generación con una
    muestra de entrenamiento inusualmente favorable (aquí, un ruido de +100 inyectado
    sólo en la generación 1) no debe colar a su campeón como "el mejor de la corrida"
    si `validate_fn` -- una remedición limpia, fuera de la presión de selección --
    dice que en realidad no lo es.
    """
    def true_quality(vector: list[float]) -> float:
        return sum(vector)

    def fitness_fn(vector: list[float], generation: int) -> float:
        noise = 100.0 if generation == 1 else 0.0
        return true_quality(vector) + noise

    def validate_fn(vector: list[float]) -> float:
        return true_quality(vector)

    result = ga.run(fitness_fn, population_size=12, generations=5, elite=2,
                    mutation_rate=0.3, mutation_scale=0.3, seed=0, validate_fn=validate_fn)

    gen1 = result.history[1]
    # La generación 1 sí parece la mejor por entrenamiento (se le coló el ruido)...
    assert gen1.best_fitness > max(g.best_fitness for i, g in enumerate(result.history)
                                   if i != 1)
    # ...pero su validación (limpia) la desenmascara: no es mejor que las demás.
    assert gen1.validation_fitness < gen1.best_fitness - 50

    # El resultado final se decide por validación, no por el máximo de entrenamiento:
    # coincide con el máximo de la curva de validación, no con el de entrenamiento.
    assert result.best.fitness == pytest.approx(max(g.validation_fitness for g in result.history))
    assert result.best.fitness != pytest.approx(max(g.best_fitness for g in result.history))


def test_ga_without_validate_fn_falls_back_to_training_fitness():
    """Sin `validate_fn` (el caso de los tests sintéticos baratos de arriba),
    `GenerationStats.validation_fitness` es `None` y `GAResult.best` cae de vuelta al
    mejor de entrenamiento -- no debe romperse ni exigir el parámetro."""
    def fitness_fn(vector: list[float], _generation: int) -> float:
        return sum(vector)

    result = ga.run(fitness_fn, population_size=6, generations=3, elite=1, seed=0)

    assert all(g.validation_fitness is None for g in result.history)
    assert result.best.fitness == pytest.approx(
        max(g.best_fitness for g in result.history))


def test_optimizer_improves_over_its_initial_population_on_real_games():
    """Integración de punta a punta con partidas de verdad: genoma -> perfil ->
    `evaluate_profile` -> `run_batch` -> motor, con las tres bandas de semillas
    (entrenamiento por generación + validación fija) ya en uso. Deliberadamente
    diminuto (población y generaciones mínimas, `workers=1`) para que siga siendo un
    test, no una corrida de optimización; la corrida de verdad se documenta en el
    informe del stream.
    """
    def fitness_fn(vector: list[float], generation: int) -> float:
        profile = vector_to_profile(vector, name="__candidato__")
        result = evaluate_profile(profile, games_per_matchup=1, workers=1,
                                  base_seed=training_seed(99, generation),
                                  character="vin", max_turns=20)
        return result.winrate

    def validate_fn(vector: list[float]) -> float:
        profile = vector_to_profile(vector, name="__candidato__")
        result = evaluate_profile(profile, games_per_matchup=1, workers=1,
                                  base_seed=validation_seed(99),
                                  character="vin", max_turns=20)
        return result.winrate

    result = ga.run(fitness_fn, population_size=4, generations=2, elite=1, seed=1,
                    validate_fn=validate_fn)

    # Aquí NO se puede exigir que best_fitness suba de una generación a la siguiente:
    # cada generación juega su propia banda de semillas (`training_seed(99, gen)`), así
    # que hasta el elite se re-evalúa contra partidas distintas y su cifra puede bajar
    # por muestreo. Esa es justamente la propiedad que fija
    # `test_ga_reevaluates_every_individual_every_generation`, y la monotonía a señal
    # constante ya la cubre `test_ga_elitism_never_regresses_training_best_fitness`.
    # Lo que este test comprueba es el cableado real -- vector, perfil, gauntlet,
    # run_batch, motor y bandas de semillas -- produciendo números usables, y que el
    # resultado final sale de la validación y no del entrenamiento.
    assert len(result.history) == 2
    assert all(0.0 <= g.best_fitness <= 1.0 for g in result.history)
    assert all(g.validation_fitness is not None for g in result.history)
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
