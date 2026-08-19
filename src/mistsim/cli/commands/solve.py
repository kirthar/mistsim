"""`mistsim solve` — abre un turno concreto y enseña la secuencia óptima.

Dos modos:

    mistsim solve --turn 6                   inspecciona ese turno: espacio de acciones,
                                             plan del solver y qué habría hecho la
                                             heurística desde el MISMO estado
    mistsim solve --duel 20                  liguilla SolverAgent vs UtilityAgent del
                                             mismo arquetipo, que es la métrica de éxito

El modo de inspección existe porque un solver que sólo devuelve un número no es
depurable: hay que poder leer la secuencia, comprobar que es legal y ver dónde gana o
pierde contra la heurística.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import random
import time

from mistsim.agents import archetypes, solver_agent
from mistsim.agents.solver_agent import SolverAgent
from mistsim.agents.utility import UtilityAgent
from mistsim.cli.common import config_from, resolve_strategies, warn_homebrew
from mistsim.content.loader import Content, load_content
from mistsim.domain.state import GameConfig, GameState
from mistsim.engine import solver
from mistsim.engine import turn as turn_engine
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.events import STATS_KINDS, EventLog
from mistsim.engine.game import GameEngine

_CONTENT: Content | None = None


def _content() -> Content:
    global _CONTENT
    if _CONTENT is None:
        _CONTENT = load_content()
    return _CONTENT


# --- inspección de un turno --------------------------------------------------


class _Snapshot(UtilityAgent):
    """Agente normal que guarda una copia del estado al empezar cada turno."""

    def __init__(self, profile, seed=None):
        super().__init__(profile, seed=seed)
        self.snapshots: dict[tuple[int, int], GameState] = {}

    def choose_action(self, state, actions):
        key = (state.turn, state.active)
        if key not in self.snapshots:
            self.snapshots[key] = state.clone()
        return super().choose_action(state, actions)


def _state_at(config: GameConfig, strategies: list[str], seed: int,
              want_turn: int, seat: int) -> GameState | None:
    """Juega una partida normal y devuelve el estado al empezar ese turno de ese asiento."""
    log = EventLog(keep=STATS_KINDS)
    engine = GameEngine(content=_content(), config=config, seed=seed, log=log)
    agents = [_Snapshot(archetypes.get(name), seed=seed + i)
              for i, name in enumerate(strategies)]
    engine.run(agents)
    return agents[seat].snapshots.get((want_turn, seat))


def _greedy_turn(state: GameState, profile) -> tuple[list[Action], dict[str, int]]:
    """Lo que haría `UtilityAgent` desde este mismo estado, para comparar de tú a tú."""
    agent = UtilityAgent(profile, seed=0)
    work = state.clone()
    log = EventLog(keep=frozenset())
    played: list[Action] = []
    for _ in range(200):
        action = agent.choose_action(work, legal_actions(work))
        if action.kind is ActionKind.END_TURN or work.finished:
            break
        turn_engine.apply(work, action, log, agent)
        played.append(action)
    res = work.player(work.active).resources
    return played, {"coin": res.coin, "combat": res.combat, "mission": res.mission}


def _describe(state: GameState) -> None:
    player = state.player(state.active)
    print(f"Turno {state.turn} · jugador {player.id} ({player.character.name}) · "
          f"salud {player.health} · quemas {player.tokens.burns_used}/"
          f"{player.tokens.burn_limit}")
    print("  mano:   " + ", ".join(i.name for i in player.hand))
    print("  aliados:" + (" " + ", ".join(i.name for i in player.allies)
                          if player.allies else " —"))
    print("  mercado:" + ", ".join(f" {i.name}({i.card.cost})" for i in state.market.row))
    print("  pistas: " + ", ".join(
        f"{t.mission.name}={t.position_of(player.id)}" for t in state.tracks))


def _measure_pruning(state: GameState, objective, config: solver.SolverConfig) -> None:
    """Cuánto recorta cada poda, medido sobre este turno concreto.

    Sólo sobre el haz (`exact_nodes=0`): con el branch-and-bound detrás las dos
    variantes gastan su presupuesto entero y el contador de nodos deja de decir nada.
    """
    print("\nEfecto de las podas (nodos del haz en este turno):")
    variants = [
        ("todo activado", True, True),
        ("sin canonicalización", False, True),
        ("sin transposiciones", True, False),
        ("sin ninguna de las dos", False, False),
    ]
    for label, canonical, dedup in variants:
        variant = solver.SolverConfig(beam_width=config.beam_width,
                                      max_depth=config.max_depth, exact_nodes=0,
                                      canonical=canonical, dedup=dedup)
        started = time.time()
        plan = solver.search_turn(state, objective, variant)
        print(f"  {label:24} {plan.explored:7d} nodos  {plan.score:7.2f} valor  "
              f"{1000 * (time.time() - started):6.0f} ms")

    legal = len(legal_actions(state))
    filtered = len(solver.candidate_actions(state))
    print(f"  lista legal {legal} acciones → {filtered} candidatas tras el filtro "
          f"({100 * (1 - filtered / max(1, legal)):.0f}% menos por paso)")


def _inspect(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    strategies = resolve_strategies(args.strategy, args.players, rng)
    config = config_from(args)
    warn_homebrew(_content(), config)

    state = _state_at(config, strategies, args.seed or 0, args.turn, args.seat)
    if state is None:
        print(f"la partida no llegó al turno {args.turn} del jugador {args.seat}")
        return 1

    _describe(state)
    profile = archetypes.get(strategies[args.seat])
    exact = 2_500 if args.exact is None else args.exact
    solver_config = solver.SolverConfig(beam_width=args.beam, max_depth=args.depth,
                                        exact_nodes=exact)

    if args.objective == "perfil":
        from mistsim.agents.solver_agent import objective_from_profile
        owned = [i.card for i in state.player(state.active).all_cards()]
        objective = objective_from_profile(
            profile, card_value=lambda card: profile.card_value(card, owned))
    else:
        objective = solver.objective_for(args.objective)

    started = time.time()
    plan = solver.solve_turn(state, objective, config=solver_config)
    elapsed = 1000 * (time.time() - started)

    print(f"\nSolver · objetivo {args.objective} · {elapsed:.0f} ms · "
          f"{plan.explored} nodos expandidos"
          f"{' · óptimo demostrado' if plan.proven else ''}")
    for i, action in enumerate(plan.actions, 1):
        if i == plan.searched + 1:
            print("      --- fases de cierre (fuera del árbol de búsqueda) ---")
        print(f"  {i:2d}. {action}")
    print(f"  → tras la búsqueda: {_fmt(plan.resources)}   valor {plan.score:.2f}"
          f"   ({plan.searched} acciones buscadas + {len(plan.actions) - plan.searched} "
          f"de cierre)")

    greedy, resources = _greedy_turn(state, profile)
    print(f"\nUtilityAgent ({profile.name}) desde el mismo estado · {len(greedy)} acciones")
    for i, action in enumerate(greedy, 1):
        print(f"  {i:2d}. {action}")
    print(f"  → al acabar el turno: {_fmt(resources)}")

    if args.podas:
        _measure_pruning(state, objective, solver_config)
    return 0


def _fmt(resources) -> str:
    return "  ".join(f"{k}={v}" for k, v in resources.items())


# --- duelo solver vs heurística ----------------------------------------------


def _play_duel(payload: tuple[str, int, int, int, int, int | None]) -> tuple[int, int, int]:
    """Una partida del duelo. Devuelve (ganó el solver, ganó la heurística, nodos).

    A nivel de módulo y con argumentos simples porque viaja a los procesos worker.
    """
    name, index, seed, turns, beam, exact = payload
    seat = index % 2                       # alternar asiento: reparte el bonus de salud
    config = GameConfig(num_players=2, max_turns=turns)
    log = EventLog(keep=STATS_KINDS)
    engine = GameEngine(content=_content(), config=config, seed=seed + index, log=log)
    profile = archetypes.get(name)
    config = solver.SolverConfig(beam_width=beam,
                                 exact_nodes=solver_agent.AGENT_CONFIG.exact_nodes
                                 if exact is None else exact)
    smart = SolverAgent(profile, seed=index, config=config)
    dumb = UtilityAgent(profile, seed=index)
    agents = [smart, dumb] if seat == 0 else [dumb, smart]
    result = engine.run(agents)
    won = result.winner == seat
    lost = result.winner is not None and not won
    return (int(won), int(lost), smart.stats["nodos"])


def _duel(args: argparse.Namespace) -> int:
    names = args.strategy or ["aggro-combate", "equilibrado", "rush-mision"]
    warn_homebrew(_content(), config_from(args))
    payloads = [(name, i, args.seed or 1000, args.turns, args.beam, args.exact)
                for name in names for i in range(args.duel)]

    started = time.time()
    workers = args.workers if args.workers > 0 else max(1, (os.cpu_count() or 2) // 2)
    if workers == 1:
        results = [_play_duel(p) for p in payloads]
    else:
        with mp.Pool(processes=min(workers, len(payloads))) as pool:
            results = pool.map(_play_duel, payloads)

    print(f"Duelo SolverAgent vs UtilityAgent · {args.duel} partidas por arquetipo · "
          f"haz {args.beam}\n")
    print(f"{'arquetipo':20} {'solver':>7} {'heurística':>11} {'tablas':>7} {'winrate':>9}")
    total = [0, 0, 0]
    for i, name in enumerate(names):
        chunk = results[i * args.duel:(i + 1) * args.duel]
        won = sum(r[0] for r in chunk)
        lost = sum(r[1] for r in chunk)
        draw = len(chunk) - won - lost
        total = [total[0] + won, total[1] + lost, total[2] + draw]
        rate = 100 * won / max(1, won + lost)
        print(f"{name:20} {won:7d} {lost:11d} {draw:7d} {rate:8.1f}%")
    rate = 100 * total[0] / max(1, total[0] + total[1])
    print(f"{'TOTAL':20} {total[0]:7d} {total[1]:11d} {total[2]:7d} {rate:8.1f}%")
    print(f"\n{time.time() - started:.0f} s · "
          f"{sum(r[2] for r in results) / len(results):.0f} nodos por partida")
    return 0


# --- entrada -----------------------------------------------------------------


def cmd_solve(args: argparse.Namespace) -> int:
    return _duel(args) if args.duel else _inspect(args)


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "solve", help="resuelve el turno óptimo y lo compara con la heurística")
    parser.add_argument("-p", "--players", type=int, default=2, choices=range(1, 5))
    parser.add_argument("-t", "--turns", type=int, default=60, help="tope de turnos")
    parser.add_argument("-s", "--seed", type=int, default=None)
    parser.add_argument("--coop", action="store_true", help="modo cooperativo")
    parser.add_argument("--strategy", nargs="*", metavar="NOMBRE",
                        help=f"disponibles: {', '.join(archetypes.names())}")
    parser.add_argument("--turn", type=int, default=5, help="turno a inspeccionar")
    parser.add_argument("--seat", type=int, default=0, help="jugador a inspeccionar")
    parser.add_argument("--objective", default="damage",
                        choices=["damage", "mission", "coin", "perfil"],
                        help="qué maximizar; 'perfil' usa los pesos del arquetipo")
    parser.add_argument("--beam", type=int, default=12, help="anchura del haz")
    parser.add_argument("--depth", type=int, default=24, help="profundidad máxima")
    parser.add_argument("--exact", type=int, default=None, metavar="N",
                        help="nodos de branch-and-bound tras el haz. Por defecto 2500 "
                             "al inspeccionar y 0 en el duelo (ver AGENT_CONFIG)")
    parser.add_argument("--podas", action="store_true",
                        help="mide cuánto recorta cada poda en ese turno")
    parser.add_argument("--duel", type=int, default=0, metavar="N",
                        help="en vez de inspeccionar, juega N partidas por arquetipo "
                             "de SolverAgent contra UtilityAgent")
    parser.add_argument("-w", "--workers", type=int, default=0)
    parser.set_defaults(func=cmd_solve)
