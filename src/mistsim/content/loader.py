"""Carga y valida el contenido JSON hacia los modelos de dominio.

Una única puerta de entrada a los datos: el motor no lee JSON en ningún sitio. Eso es lo
que permite sustituir el contenido homebrew por datos reales editando sólo `data/`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mistsim.domain.cards import Ability, Card, CardType
from mistsim.domain.metals import Metal
from mistsim.domain.missions import Mission, MissionReward
from mistsim.domain.player import Character

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class ContentError(Exception):
    """Los datos no cuadran con lo que el motor espera."""


def _metal(value: str | None) -> Metal | None:
    if value is None:
        return None
    try:
        return Metal(value)
    except ValueError as exc:
        raise ContentError(f"metal desconocido: {value!r}") from exc


def _ability(raw: dict | None, *, extra_burns: int = 0) -> Ability | None:
    if not raw:
        return None
    # metal None = no pide quema (las cartas de Financiación).
    return Ability(
        metal=_metal(raw.get("metal")),
        effects=dict(raw.get("effects") or {}),
        extra_burns=raw.get("extra_burns", extra_burns),
    )


def _card(raw: dict) -> Card:
    secondary_raw = raw.get("secondary")
    return Card(
        name=raw["name"],
        type=CardType(raw["type"]),
        cost=raw["cost"],
        metal_pair=tuple(_metal(m) for m in raw.get("metal_pair", [])),  # type: ignore[misc]
        primary=_ability(raw.get("primary")),
        secondary=_ability(secondary_raw),
        savant=raw.get("savant"),
        off_turn=raw.get("off_turn"),
        ongoing=raw.get("ongoing"),
        defense=raw.get("defense"),
        copies=raw.get("copies", 1),
        card_number=raw.get("card_number"),
    )


@dataclass(frozen=True)
class Content:
    """Todo el contenido de una partida, ya validado."""

    market: tuple[Card, ...]
    funding: Card
    #: Los 8 diseños de Entrenamiento, uno por metal.
    training: tuple[Card, ...]
    #: id de personaje -> los 4 metales de Entrenamiento que le tocan.
    training_sets: dict[str, tuple[str, ...]]
    characters: tuple[Character, ...]
    missions: tuple[Mission, ...]
    lord_ruler: tuple[dict, ...]
    #: Qué partes provienen de datos reales verificados y cuáles son homebrew.
    provenance: dict[str, bool]

    def market_by_name(self, name: str) -> Card:
        for card in self.market:
            if card.name == name:
                return card
        raise KeyError(name)

    def character(self, char_id: str) -> Character:
        for c in self.characters:
            if c.id == char_id:
                return c
        raise KeyError(char_id)

    def starting_deck(self, char_id: str) -> list[Card]:
        """Las 10 cartas de salida: las 4 de Entrenamiento del personaje + 6 Financiaciones."""
        metals = self.training_sets[char_id]
        by_metal = {c.primary.metal.value: c for c in self.training if c.primary}
        deck = [by_metal[m] for m in metals]
        deck += [self.funding] * self.funding.copies
        return deck


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise ContentError(f"falta el fichero de datos: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_content(data_dir: Path | None = None) -> Content:
    root = data_dir or DATA_DIR

    market_raw = _load_json(root / "market_cards.json")
    market = tuple(_card(c) for c in market_raw["cards"])

    starter = _load_json(root / "starter_deck.json")
    funding = _card(starter["funding"])
    training = tuple(_card(c) for c in starter["training"])
    training_sets = {k: tuple(v) for k, v in starter["character_training_sets"].items()}

    chars_raw = _load_json(root / "characters.json")
    characters = tuple(
        Character(
            id=c["id"], name=c["name"], title=c["title"],
            signature_metal=c["signature_metal"],
            level_1_effects=c["level_1_ability"]["effects"],
            promo=c.get("promo", False),
        )
        for c in chars_raw["characters"]
    )

    missions_raw = _load_json(root / "missions.json")
    missions = tuple(_mission(m) for m in missions_raw["missions"])

    lr_raw = _load_json(root / "lord_ruler.json")

    validate(market, missions, lr_raw)

    return Content(
        market=market, funding=funding, training=training,
        training_sets=training_sets,
        characters=characters, missions=missions,
        lord_ruler=tuple(lr_raw["cards"]),
        provenance={
            "market_cards": True,
            "characters": True,
            "starter_deck": starter["_meta"].get("verified", False),
            "missions": missions_raw["_meta"].get("verified", False),
            "lord_ruler": lr_raw["_meta"].get("verified", False),
        },
    )


def _mission(raw: dict) -> Mission:
    return Mission(
        name=raw["name"],
        starting_bonus=raw.get("starting_bonus"),
        rewards=tuple(
            MissionReward(
                position=r["position"],
                effects=r["effects"],
                first_player_bonus=r.get("first_player_bonus"),
            )
            for r in raw.get("rewards", [])
        ),
        top_reward=raw.get("top_reward"),
        top_reward_first_bonus=raw.get("top_reward_first_bonus"),
        verified=raw.get("verified", False),
        source=raw.get("source", "homebrew"),
    )


def validate(market: tuple[Card, ...], missions: tuple[Mission, ...],
             lord_ruler: dict) -> None:
    """Comprobaciones de integridad que deben cumplirse siempre."""
    names = [c.name for c in market]
    if len(set(names)) != len(names):
        raise ContentError("hay nombres de carta repetidos en el Mercado")
    if len(market) != 65:
        raise ContentError(f"se esperaban 65 cartas de Mercado, hay {len(market)}")

    physical = sum(c.copies for c in market)
    if physical != 82:
        raise ContentError(f"se esperaban 82 cartas físicas, suman {physical}")

    numbers = [c.card_number for c in market if c.card_number]
    if len(numbers) == 65:
        if len(set(numbers)) != 65:
            raise ContentError("números de carta repetidos")
        gaps = set(range(1, 83)) - set(numbers)
        dupes = sum(1 for c in market if c.copies == 2)
        if len(gaps) != dupes:
            raise ContentError(
                f"{len(gaps)} huecos de numeración pero {dupes} cartas de 2 copias; "
                "el set no cuadra"
            )

    for card in market:
        if card.secondary and not card.primary:
            raise ContentError(f"{card.name}: tiene secundaria sin primaria")
        if card.secondary and card.secondary.extra_burns < 1:
            raise ContentError(f"{card.name}: la secundaria debe pedir >= 1 quema extra")
        if card.is_ally and card.defense is None:
            raise ContentError(f"{card.name}: Aliado sin valor de Defensa")

    if len(missions) < 3:
        raise ContentError(f"hacen falta al menos 3 Misiones, hay {len(missions)}")

    lr_cards = lord_ruler.get("cards", [])
    if len(lr_cards) != 36:
        raise ContentError(f"el mazo del Lord Ruler debe tener 36 cartas, tiene {len(lr_cards)}")
