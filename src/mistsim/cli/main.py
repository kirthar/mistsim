"""Interfaz de línea de comandos de mistsim."""
from __future__ import annotations

import argparse
import collections
import random
import sys

from mistsim.agents import archetypes
from mistsim.agents.synergy import explain
from mistsim.agents.tags import tags_for
from mistsim.agents.utility import UtilityAgent
from mistsim.content.loader import ContentError, load_content
from mistsim.domain.state import GameConfig, Mode
from mistsim.engine.game import GameEngine
from mistsim.report import log as report_log


def _agents(names: list[str], seed: int) -> list[UtilityAgent]:
    return [UtilityAgent(archetypes.get(n), seed=seed + i) for i, n in enumerate(names)]


def _resolve_strategies(raw: list[str] | None, players: int, rng: random.Random) -> list[str]:
    if not raw:
        return [rng.choice(archetypes.names()) for _ in range(players)]
    if len(raw) == 1:
        return raw * players
    if len(raw) != players:
        raise SystemExit(f"se dieron {len(raw)} estrategias para {players} jugadores")
    return raw


# --- play --------------------------------------------------------------------


def cmd_play(args: argparse.Namespace) -> int:
    content = load_content()
    rng = random.Random(args.seed)
    strategies = _resolve_strategies(args.strategy, args.players, rng)

    config = GameConfig(
        mode=Mode.COOP if args.coop else Mode.PVP,
        num_players=args.players, max_turns=args.turns,
    )
    engine = GameEngine(content=content, config=config, seed=args.seed)
    result = engine.run(_agents(strategies, args.seed or 0), characters=args.characters)

    print("Estrategias: " + ", ".join(f"P{i}={s}" for i, s in enumerate(strategies)))
    if config.mode is Mode.COOP or not content.provenance["missions"]:
        _warn_homebrew(content, config)
    print()
    print(report_log.render(result.log, verbose=args.verbose))
    print(report_log.summary(result))
    return 0


def _warn_homebrew(content, config: GameConfig) -> None:
    gaps = [k for k, ok in content.provenance.items() if not ok]
    if config.mode is not Mode.COOP:
        gaps = [g for g in gaps if g != "lord_ruler"]
    if gaps:
        print(f"AVISO: esta partida usa datos homebrew ({', '.join(gaps)}); "
              f"no son valores del juego real.", file=sys.stderr)


# --- batch -------------------------------------------------------------------


def cmd_batch(args: argparse.Namespace) -> int:
    content = load_content()
    rng = random.Random(args.seed)
    strategies = _resolve_strategies(args.strategy, args.players, rng)
    config = GameConfig(
        mode=Mode.COOP if args.coop else Mode.PVP,
        num_players=args.players, max_turns=args.turns,
    )

    wins = collections.Counter()
    reasons = collections.Counter()
    turns_total = 0

    for n in range(args.games):
        engine = GameEngine(content=content, config=config, seed=(args.seed or 0) + n)
        result = engine.run(_agents(strategies, n))
        reasons[result.reason] += 1
        turns_total += result.turns
        if result.winner is not None:
            wins[strategies[result.winner]] += 1
        else:
            wins["<sin ganador>"] += 1

    print(f"{args.games} partidas · {args.players} jugadores · {config.mode}")
    print(f"Duración media: {turns_total / args.games:.1f} turnos\n")

    print("Victorias por estrategia:")
    counts = collections.Counter(strategies)
    for name, won in wins.most_common():
        seats = counts.get(name, 0)
        # Con la misma estrategia en varios asientos, el reparto justo es 1/asientos.
        expected = f" (esperado {100 * seats / args.players:.0f}%)" if seats else ""
        print(f"  {name:20} {won:5}  {100 * won / args.games:5.1f}%{expected}")

    print("\nCómo terminan:")
    for reason, count in reasons.most_common():
        print(f"  {reason:26} {count:5}  {100 * count / args.games:5.1f}%")
    return 0


# --- tourney -----------------------------------------------------------------


def cmd_tourney(args: argparse.Namespace) -> int:
    """Todos contra todos: enfrenta cada par de arquetipos."""
    content = load_content()
    names = args.strategy or archetypes.names()
    config = GameConfig(num_players=2, max_turns=args.turns)

    record: dict[str, list[int]] = {n: [0, 0] for n in names}  # [ganadas, jugadas]
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            for game_no in range(args.games):
                # Alterna quién empieza, porque el orden de turno da bonus de salud.
                order = [first, second] if game_no % 2 == 0 else [second, first]
                engine = GameEngine(content=content, config=config,
                                    seed=(args.seed or 0) + game_no)
                result = engine.run(_agents(order, game_no))
                for name in order:
                    record[name][1] += 1
                if result.winner is not None:
                    record[order[result.winner]][0] += 1

    print(f"Liguilla · {args.games} partidas por emparejamiento · "
          f"{len(names)} arquetipos\n")
    print(f"{'estrategia':22} {'winrate':>8}  {'V':>5}/{'J':<5}")
    ranked = sorted(record.items(), key=lambda kv: -kv[1][0] / max(1, kv[1][1]))
    for name, (won, played) in ranked:
        rate = 100 * won / played if played else 0
        print(f"{name:22} {rate:7.1f}%  {won:5}/{played:<5}")
    return 0


# --- validate ----------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        content = load_content()
    except ContentError as exc:
        print(f"CONTENIDO INVÁLIDO: {exc}", file=sys.stderr)
        return 1

    print("Contenido válido.\n")
    print(f"  Mercado           {len(content.market)} nombres, "
          f"{sum(c.copies for c in content.market)} cartas físicas")
    print(f"  Personajes        {len(content.characters)} "
          f"({', '.join(c.id for c in content.characters)})")
    print(f"  Misiones          {len(content.missions)}")
    print(f"  Lord Ruler        {len(content.lord_ruler)} cartas")
    print(f"  Arquetipos        {len(archetypes.names())}")

    print("\nProcedencia de los datos:")
    for source, verified in content.provenance.items():
        mark = "verificado" if verified else "HOMEBREW — valores inventados"
        print(f"  {source:18} {mark}")

    unverified = [k for k, v in content.provenance.items() if not v]
    if unverified:
        print("\nLo que falta por fotografiar para que la simulación sea fiel:")
        if "missions" in unverified:
            print("  · las 8 cartas de Misión (valores numéricos de cada pista)")
        if "lord_ruler" in unverified:
            print("  · las 36 cartas del Lord Ruler (Adversarios y Edictos)")
        print("\n  Hasta entonces, los resultados del modo Coop y el peso de las")
        print("  Misiones en PvP no reflejan el juego real.")
    return 0


# --- cards -------------------------------------------------------------------


def cmd_cards(args: argparse.Namespace) -> int:
    content = load_content()
    cards = sorted(content.market, key=lambda c: (c.cost, c.name))

    if args.metal:
        cards = [c for c in cards if any(str(m).lower() == args.metal.lower()
                                         for m in c.metal_pair)]
    if args.tag:
        cards = [c for c in cards
                 if any(t.value == args.tag.lower() for t in tags_for(c))]
    if args.max_cost is not None:
        cards = [c for c in cards if c.cost <= args.max_cost]

    if args.name:
        card = content.market_by_name(args.name)
        return _show_card(content, card)

    print(f"{'coste':>5} {'nombre':22} {'tipo':7} {'metales':16} etiquetas")
    for card in cards:
        metals = "/".join(str(m) for m in card.metal_pair) or "—"
        tags = ",".join(sorted(t.value for t in tags_for(card)))
        print(f"{card.cost:5} {card.name:22} {card.type.value:7} {metals:16} {tags}")
    print(f"\n{len(cards)} cartas")
    return 0


def _show_card(content, card) -> int:
    print(f"{card.name}  ({card.card_number}/82)")
    print(f"  tipo      {card.type.value}   coste {card.cost}   copias {card.copies}")
    if card.defense is not None:
        print(f"  defensa   {card.defense}")
    print(f"  metales   {'/'.join(str(m) for m in card.metal_pair) or '—'}")
    if card.primary:
        print(f"  primaria  [{card.primary.metal}] {dict(card.primary.effects)}")
    if card.secondary:
        print(f"  +{card.secondary.extra_burns} {card.secondary.metal}  "
              f"{dict(card.secondary.effects)}")
    if card.savant:
        print(f"  savant    {dict(card.savant)}  (sólo jugándola de lado como metal)")
    if card.off_turn:
        print(f"  fuera de turno  {dict(card.off_turn)}")
    if card.ongoing:
        print(f"  permanente      {card.ongoing}")
    print(f"  etiquetas {', '.join(sorted(t.value for t in tags_for(card)))}")

    others = [c for c in content.market if c.name != card.name]
    rules = explain(card, others)
    if rules:
        print("\n  Sinergias posibles (con todo el Mercado como referencia):")
        for name, value, why in rules:
            print(f"    +{value:4.1f}  {name}")
            print(f"           {why}")
    return 0


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mistsim",
        description="Simulador de Mistborn: The Deckbuilding Game")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_game_args(sp):
        sp.add_argument("-p", "--players", type=int, default=2, choices=range(1, 5))
        sp.add_argument("-t", "--turns", type=int, default=60, help="tope de turnos")
        sp.add_argument("-s", "--seed", type=int, default=None)
        sp.add_argument("--coop", action="store_true", help="modo cooperativo")
        sp.add_argument("--strategy", nargs="*", metavar="NOMBRE",
                        help=f"una por jugador. Disponibles: {', '.join(archetypes.names())}")

    play = sub.add_parser("play", help="juega una partida y muestra el log turno a turno")
    add_game_args(play)
    play.add_argument("-v", "--verbose", action="store_true")
    play.add_argument("--characters", nargs="*", metavar="ID")
    play.set_defaults(func=cmd_play)

    batch = sub.add_parser("batch", help="juega N partidas y resume los resultados")
    add_game_args(batch)
    batch.add_argument("-n", "--games", type=int, default=100)
    batch.set_defaults(func=cmd_batch)

    tourney = sub.add_parser("tourney", help="liguilla de todos los arquetipos contra todos")
    tourney.add_argument("-n", "--games", type=int, default=20)
    tourney.add_argument("-t", "--turns", type=int, default=60)
    tourney.add_argument("-s", "--seed", type=int, default=None)
    tourney.add_argument("--strategy", nargs="*", metavar="NOMBRE")
    tourney.set_defaults(func=cmd_tourney)

    validate = sub.add_parser("validate", help="comprueba los datos e informa de su procedencia")
    validate.set_defaults(func=cmd_validate)

    cards = sub.add_parser("cards", help="consulta el Mercado")
    cards.add_argument("name", nargs="?", help="ficha detallada de una carta")
    cards.add_argument("--metal")
    cards.add_argument("--tag")
    cards.add_argument("--max-cost", type=int)
    cards.set_defaults(func=cmd_cards)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
