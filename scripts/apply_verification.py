"""Aplica a market_cards.json las correcciones leídas de las imágenes de carta.

La imagen manda: cada campo aquí se re-derivó de un recorte ampliado (scripts/zoom.py).
Idempotente sólo sobre el JSON original — se ejecutó una vez y su salida está commiteada;
se conserva como registro auditable de qué se cambió y por qué.
"""
import copy
import json

SRC = "data/market_cards.json"

CARD_NUMBERS = {
    "Ascendant": 36, "Assassinate": 53, "Balance": 3, "Brawl": 44, "Charm": 70,
    "Coinshot": 60, "Con": 11, "Confrontation": 4, "Coppercloud": 29, "Crash": 39,
    "Crewleader": 66, "Cushing Blow": 45, "Deceive": 13, "Dominate": 9, "Eavesdrop": 65,
    "Enrage": 74, "Hazekillers": 82, "Hide": 31, "House Lord": 68, "House War": 72,
    "Hunt": 20, "Hyperaware": 63, "Infiltrate": 16, "Informant": 14, "Inquisitor": 6,
    "Inspire": 76, "Intimidate": 71, "Investigate": 67, "Ironpull": 37, "Kandra": 5,
    "Keeper": 32, "Lookout": 61, "Lurcher": 42, "Maelstrom": 54, "Mercenary": 59,
    "Noble": 79, "Obligator": 21, "Pacify": 7, "Pewterarm": 51, "Pickpocket": 46,
    "Pierce": 18, "Precise Shot": 52, "Preserve": 1, "Pursue": 17, "Rebel": 77,
    "Recover": 43, "Reposition": 34, "Rescue": 35, "Rioter": 78, "Ruin": 2,
    "Seeker": 24, "Smoker": 33, "Sneak": 25, "Soar": 56, "Soldier": 50, "Soother": 15,
    "Spy": 62, "Steelpush": 58, "Strategize": 27, "Strike": 47, "Subdue": 8,
    "Survive": 48, "Tineye": 69, "Train in Secret": 26, "Unveil": 23,
}

# nombre -> [(ruta, valor correcto, motivo)]
FIXES = {
    "Ascendant": [("secondary.extra_burns", 2, 'la carta imprime "+2 IRON"')],
    "Assassinate": [("primary.effects.combat", 3, "las espadas muestran 3, no 1")],
    "Coppercloud": [("primary.effects.coin", 1, "moneda 1 omitida en el JSON")],
    "Crash": [
        ("primary.effects.combat", 2, "las espadas muestran 2, no 1"),
        ("savant", {"combat": 2}, "savant omitido (el vial muestra combate 2)"),
    ],
    "Cushing Blow": [
        ("name", "Crushing Blow", 'el nombre impreso es "Crushing Blow"'),
        ("secondary.extra_burns", 2, 'la carta imprime "+2 PEWTER"'),
    ],
    "Dominate": [("secondary.extra_burns", 2, 'la carta imprime "+2 BRASS"')],
    "Eavesdrop": [("savant", {"coin": 1}, "savant omitido")],
    "Hide": [("savant", {"combat": 2}, "savant omitido")],
    "House War": [
        ("primary.effects.combat", 2, "combate 2 omitido en el JSON"),
        ("secondary.extra_burns", 2, 'la carta imprime "+2 ZINC"'),
    ],
    "Hyperaware": [("secondary.extra_burns", 2, 'la carta imprime "+2 TIN"')],
    "Infiltrate": [
        ("primary.effects", {"combat": 2, "coin": 2}, "el primer glifo es espadas, no misión"),
        ("secondary.effects", {"combat": 1, "mission": 2}, "combate 1 omitido"),
    ],
    "Lookout": [
        ("primary.effects", {"mission": 2}, "glifo cuadrado (misión), no círculo (moneda)"),
    ],
    "Lurcher": [("primary.effects.combat", 2, "las espadas muestran 2, no 1")],
    "Maelstrom": [("secondary.extra_burns", 2, 'la carta imprime "+2 STEEL"')],
    "Noble": [("defense", 2, "el escudo muestra 2, no 3")],
    "Pacify": [("savant", {"train": 1}, "savant omitido")],
    "Precise Shot": [("primary.effects.combat", 3, "las espadas muestran 3, no 1")],
    "Pursue": [("savant", {"mission": 1}, "savant omitido")],
    "Reposition": [("savant", {"combat": 1}, "savant omitido")],
    "Rescue": [("primary.effects.combat", 3, "las espadas muestran 3, no 1")],
    "Soar": [("savant", {"mission": 1}, "savant omitido")],
    "Steelpush": [
        ("primary.effects", {"choice_of": ["train:1", "combat:3"]},
         "es una elección entrenamiento/combate, con valores 1 y 3"),
        ("secondary.effects", {"combat": 1, "mission": 2},
         "glifo cuadrado (misión), no círculo (moneda)"),
    ],
    "Strategize": [
        ("secondary.effects",
         {"choice_of": ["train:1", "combat:4", "mission:3", "heal:5", "coin:5"]},
         "faltaba la opción de misión y el combate es 4, no 3"),
    ],
    "Strike": [("savant", {"heal": 1}, "savant omitido")],
    "Train in Secret": [
        ("primary.effects", {"choice_of": ["train:1", "combat:2", "mission:2", "heal:3"]},
         "glifo cuadrado (misión), no círculo (moneda)"),
    ],
}


def get_path(card, path):
    node = card
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def set_path(card, path, value):
    parts = path.split(".")
    node = card
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def main() -> None:
    data = json.load(open(SRC))
    cards = data["cards"]

    # El número va antes que los arreglos, porque uno de ellos renombra una carta.
    for card in cards:
        card["card_number"] = CARD_NUMBERS[card["name"]]
        card["verified_from_image"] = True

    diffs = []
    for name, fixes in FIXES.items():
        card = next(c for c in cards if c["name"] == name)
        for path, value, why in fixes:
            was = copy.deepcopy(get_path(card, path))
            set_path(card, path, value)
            diffs.append({"card": name, "field": path, "was": was, "now": value, "why": why})

    cards.sort(key=lambda c: c["card_number"])
    data["_meta"]["verification"] = (
        "Las 65 cartas re-derivadas una a una de sus imágenes (recortes ampliados x4/x5); "
        "la imagen manda sobre cualquier transcripción previa. "
        f"{len(FIXES)} cartas corregidas, ver data/verify/DIFF.md. Integridad: 65 números "
        "de carta distintos sobre 82, con 17 huecos = las 17 cartas de 2 copias."
    )

    json.dump(data, open(SRC, "w"), indent=2, ensure_ascii=False)
    json.dump(diffs, open("data/verify/diffs.json", "w"), indent=2, ensure_ascii=False)
    print(f"{len(diffs)} correcciones sobre {len(FIXES)} cartas")


if __name__ == "__main__":
    main()
