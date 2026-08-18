"""`mistsim optimize` — algoritmo genético sobre `StrategyProfile`.

Deriva la política de compra óptima para un personaje concreto, en vez de usar uno de
los 11 arquetipos escritos a mano. El fitness es el winrate contra un gauntlet FIJO de
esos 11 arquetipos (nunca autojuego — ver `mistsim.optimize.fitness`), así que el
número de la generación 40 es comparable con el de la generación 5.

Presupuesto de cómputo, para elegir `--population`/`--generations`/`--games` con
conocimiento de causa:

    partidas totales = población x 11 rivales x --games x 2 asientos x generaciones

Medido en esta máquina (4 núcleos, `collect_log=False`): ~85-90 partidas/s. Los valores
por defecto (24 x 11 x 4 x 2 x 12 = 25 344 partidas) tardan unos 5 minutos con
`-w 0` (todos los núcleos). `--quick` (8 x 11 x 1 x 2 x 4 = 704 partidas) tarda
segundos y sirve para comprobar que el comando funciona antes de lanzar una corrida
larga.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mistsim.cli.common import warn_homebrew
from mistsim.content.loader import load_content
from mistsim.domain.state import GameConfig
from mistsim.io import serial
from mistsim.optimize import ga
from mistsim.optimize.fitness import GAUNTLET, evaluate_profile
from mistsim.optimize.genome import vector_to_profile

#: Preset completo: termina en minutos, no horas (ver cabecera del módulo).
_FULL = {"population": 24, "generations": 12, "games": 4}
#: Preset de humo: sólo para comprobar que el comando funciona de punta a punta.
_QUICK = {"population": 8, "generations": 4, "games": 1}

#: Partidas de sobra para medir el perfil final con más precisión que durante la
#: búsqueda, sin repetir el coste de una generación entera.
_FINAL_EVAL_MIN_GAMES = 8


def cmd_optimize(args: argparse.Namespace) -> int:
    content = load_content()
    pool = sorted(c.id for c in content.characters if not c.promo)
    if args.character not in pool:
        raise SystemExit(f"personaje desconocido: {args.character!r}. Disponibles: {pool}")

    warn_homebrew(content, GameConfig(max_turns=args.turns))

    preset = _QUICK if args.quick else _FULL
    population = args.population if args.population is not None else preset["population"]
    generations = args.generations if args.generations is not None else preset["generations"]
    games = args.games if args.games is not None else preset["games"]

    total_games = population * len(GAUNTLET) * games * 2 * generations
    print(f"mistsim optimize · personaje={args.character} · "
          f"población={population} generaciones={generations} "
          f"partidas/emparejamiento={games} · gauntlet={len(GAUNTLET)} arquetipos")
    print(f"presupuesto: hasta {total_games} partidas "
          f"(población x {len(GAUNTLET)} rivales x {games} partidas x 2 asientos x "
          f"{generations} generaciones)\n")

    def fitness_fn(vector: list[float]) -> float:
        profile = vector_to_profile(vector, name="__ga__")
        result = evaluate_profile(
            profile, games_per_matchup=games, workers=args.workers,
            base_seed=args.seed, character=args.character, max_turns=args.turns)
        return result.winrate

    def on_generation(stats: ga.GenerationStats) -> None:
        print(f"  gen {stats.generation:3d}  mejor={stats.best_fitness:6.1%}  "
              f"media={stats.mean_fitness:6.1%}  peor={stats.worst_fitness:6.1%}")

    start = time.time()
    result = ga.run(
        fitness_fn, population_size=population, generations=generations,
        elite=min(args.elite, population), mutation_rate=args.mutation_rate,
        mutation_scale=args.mutation_scale, tournament_k=args.tournament_k,
        seed=args.seed, on_generation=on_generation)
    elapsed = time.time() - start

    name = args.name or f"optimizado-{args.character}"
    description = (f"Derivado por `mistsim optimize` para {args.character}: "
                   f"{generations} generaciones, población {population}, gauntlet de "
                   f"{len(GAUNTLET)} arquetipos.")
    best_profile = vector_to_profile(result.best.vector, name=name, description=description)

    # Con más partidas por emparejamiento que durante la búsqueda: el ganador ya está
    # elegido, así que aquí el gasto es en medirlo mejor, no en seguir buscando.
    final_games = max(games, _FINAL_EVAL_MIN_GAMES)
    breakdown = evaluate_profile(
        best_profile, games_per_matchup=final_games, workers=args.workers,
        base_seed=args.seed + 999_983, character=args.character, max_turns=args.turns)

    print(f"\nTerminado en {elapsed:.1f}s ({elapsed / max(1, generations):.1f}s/generación).")
    print(f"Mejor perfil: {name}")
    print(f"  winrate (gauntlet completo):         {breakdown.winrate:6.1%}  "
          f"({breakdown.wins}/{breakdown.games})")
    print(f"  winrate SIN victoria por Misiones:    {breakdown.winrate_sin_mision:6.1%}  "
          f"({breakdown.wins_sin_mision}/{breakdown.games}, de las cuales "
          f"{breakdown.mission_wins} victorias totales fueron por Misiones)")
    print("  Las Misiones son datos homebrew (ver README/CONTRIBUTING): la brecha entre "
          "las dos cifras de arriba es cuánto del winrate depende de ese atajo "
          "inventado, no sólo de la estrategia real.")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = serial.profile_to_dict(best_profile)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"\nPerfil guardado en {out_path}")
        print("Cárgalo con: mistsim.io.serial.profile_from_dict(json.load(open(...)))")

    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "optimize",
        help="algoritmo genético: deriva la política de compra óptima para un personaje")
    parser.add_argument("--character", required=True,
                        help="personaje objetivo (p.ej. vin, kelsier, shan, marsh)")
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--population", type=int, default=None)
    parser.add_argument("--games", type=int, default=None, metavar="N",
                        help="partidas por rival y asiento durante la búsqueda")
    parser.add_argument("--quick", action="store_true",
                        help="preset de humo (segundos en vez de minutos), para probar "
                             "que el comando funciona antes de una corrida larga")
    parser.add_argument("-w", "--workers", type=int, default=0,
                        help="procesos en paralelo; 0 = todos los núcleos, 1 = sin "
                             "paralelizar. Con otras líneas de trabajo usando la misma "
                             "CPU, considera -w 2 en corridas largas.")
    parser.add_argument("-s", "--seed", type=int, default=0)
    parser.add_argument("-t", "--turns", type=int, default=60, help="tope de turnos por partida")
    parser.add_argument("--elite", type=int, default=2,
                        help="individuos que pasan intactos a la siguiente generación")
    parser.add_argument("--mutation-rate", type=float, default=0.15,
                        help="probabilidad de mutar cada gen")
    parser.add_argument("--mutation-scale", type=float, default=0.2,
                        help="desviación típica del ruido gaussiano de mutación")
    parser.add_argument("--tournament-k", type=int, default=3,
                        help="tamaño del torneo de selección")
    parser.add_argument("--name", default=None, help="nombre del perfil resultante")
    parser.add_argument("--output", metavar="RUTA.json",
                        help="guarda el perfil optimizado como JSON, cargable como un "
                             "arquetipo más")
    parser.set_defaults(func=cmd_optimize)
