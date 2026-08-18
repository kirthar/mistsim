"""Genera el mazo homebrew de 36 cartas del Lord Ruler.

HUECO DE DATOS: ninguna de las 36 cartas reales está transcrita ni publicada. Lo que sí
está documentado en el manual y el FAQ es su *estructura*, y es eso lo que se respeta:

- Adversarios: 1-3 escudos, valor X = Dominance actual, se destruyen de izquierda a
  derecha, y llevan un efecto negativo permanente o de fin de turno para el jugador
  al que se asignan.
- Edictos: hasta 4 efectos secuenciales — subida de Dominance, un efecto negativo,
  curación del Lord Ruler (10 por Misión sin completar, máx. 48) y limpieza de mercado.

Se genera por plantilla en vez de a mano para que la curva sea explícita y auditable:
los Adversarios se endurecen conforme avanza el mazo, y los Edictos se reparten para
que la Dominance suba de forma repartida en toda la partida.
"""
import json

# (nombre, escudos, efecto, cuándo aplica)
ADVERSARIES = [
    ("Steel Inquisitor",   ["X"],           {"damage": 3},                    "end_of_turn"),
    ("Koloss Brute",       ["X", "X"],      {"damage": 4},                    "end_of_turn"),
    ("Hazekiller Squad",   [3],             {"block_ally_activation": 1},     "permanent"),
    ("Obligator Inspector",[2],             {"coin_penalty": 1},              "permanent"),
    ("Canton Enforcer",    ["X", 3],        {"mission_penalty": 1},           "permanent"),
    ("Mistwraith",         [2, 2],          {"damage": 2},                    "end_of_turn"),
    ("Garrison Captain",   ["X", "X", 2],   {"damage": 5},                    "end_of_turn"),
    ("Thug Enforcer",      [3, 3],          {"burn_limit_penalty": 1},        "permanent"),
    ("Seeker Adjunct",     [2],             {"block_seek": 1},                "permanent"),
    ("Lurcher Sentinel",   ["X", 2],        {"block_pull": 1},                "permanent"),
    ("Soother Agent",      [3],             {"discard_penalty": 1},           "end_of_turn"),
    ("Koloss Warband",     ["X", "X", "X"], {"damage": 6},                    "end_of_turn"),
    ("Inquisitor Prime",   [4, 4],          {"damage": 5},                    "end_of_turn"),
    ("Ministry Overseer",  ["X", 3, 3],     {"mission_penalty": 2},           "permanent"),
    ("Kandra Impostor",    [2, 2],          {"block_market_buy_above": 5},    "permanent"),
    ("Tineye Watcher",     [3],             {"block_sense": 1},               "permanent"),
]

# (nombre, subida de Dominance, efecto adicional, ¿cura?, ¿limpia mercado?)
EDICTS = [
    ("Decree of Ash",        1, {"damage": 2},                   True,  False),
    ("Skaa Purge",           1, {"collective_damage": 3},        False, True),
    ("Iron Ministry Edict",  1, {"eliminate_from_hand": 1},      True,  False),
    ("Mists of Judgment",    2, {"collective_damage": 4},        True,  False),
    ("Tribute Levy",         1, {"coin_penalty": 2},             False, True),
    ("Ashfall",              1, {"damage": 3},                   True,  False),
    ("Inquisition",          2, {"eliminate_from_hand": 2},      True,  True),
    ("Martial Law",          1, {"block_market_buy_above": 6},   False, True),
    ("Steel Ministry Purge", 1, {"collective_damage": 5},        True,  False),
    ("Lord Ruler's Gaze",    2, {"mission_penalty": 2},          True,  False),
    ("Curfew",               1, {"draw_penalty": 1},             False, True),
    ("Ascendant Warning",    1, {"collective_damage": 4},        True,  False),
    ("Final Empire Decree",  2, {"damage": 5},                   True,  True),
    ("Terris Betrayal",      1, {"eliminate_from_hand": 1},      True,  False),
    ("Koloss Muster",        1, {"collective_damage": 6},        True,  False),
    ("Hemalurgic Spike",     2, {"burn_limit_penalty": 1},       True,  False),
    ("Well of Ascension",    1, {"collective_damage": 5},        True,  True),
    ("The Deepness Stirs",   2, {"damage": 6},                   True,  False),
    ("Reign Eternal",        2, {"collective_damage": 7},        True,  True),
    ("Sazed's Doubt",        1, {"draw_penalty": 1},             True,  False),
]


def build() -> dict:
    cards = []
    for i, (name, shields, effect, timing) in enumerate(ADVERSARIES):
        cards.append({
            "id": f"adv_{i:02d}", "name": name, "type": "Adversary",
            "shields": shields, "effect": effect, "timing": timing,
        })
    for i, (name, dom, effect, heals, clears) in enumerate(EDICTS):
        cards.append({
            "id": f"edict_{i:02d}", "name": name, "type": "Edict",
            "dominance_increase": dom, "effect": effect,
            "heals_lord_ruler": heals, "clears_market": clears,
        })
    return {
        "_meta": {
            "verified": False,
            "source": "homebrew",
            "note": (
                "HUECO DE DATOS. Ninguna de las 36 cartas reales del mazo del Lord Ruler "
                "está transcrita ni publicada en ninguna fuente. Estas 36 respetan la "
                "estructura documentada en el manual y el FAQ (escudos 1-3, X = Dominance "
                "actual, Edictos con hasta 4 efectos secuenciales), pero sus nombres y "
                "valores son inventados. Un resultado de modo Coop NO es un resultado del "
                "juego real."
            ),
            "action_item": "Fotografiar las 36 cartas del Lord Ruler.",
            "generated_by": "scripts/gen_lord_ruler.py",
        },
        "lord_ruler": {
            "starting_health": 48,
            "dominance_start": 1,
            "dominance_max": 6,
            "heal_per_incomplete_mission": 10,
            "market_cards_cleared": 2,
        },
        "cards": cards,
    }


if __name__ == "__main__":
    data = build()
    assert len(data["cards"]) == 36, len(data["cards"])
    with open("data/lord_ruler.json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"{len(ADVERSARIES)} Adversarios + {len(EDICTS)} Edictos = {len(data['cards'])} cartas")
