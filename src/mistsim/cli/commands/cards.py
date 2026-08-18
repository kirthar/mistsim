"""`mistsim cards` — consulta el Mercado."""
from __future__ import annotations

import argparse

from mistsim.agents.synergy import explain
from mistsim.agents.tags import tags_for
from mistsim.content.loader import load_content


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


def register(subparsers) -> None:
    parser = subparsers.add_parser("cards", help="consulta el Mercado")
    parser.add_argument("name", nargs="?", help="ficha detallada de una carta")
    parser.add_argument("--metal")
    parser.add_argument("--tag")
    parser.add_argument("--max-cost", type=int)
    parser.set_defaults(func=cmd_cards)
