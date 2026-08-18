"""Estrategias: que sean distintas de verdad, no sólo de nombre."""
import pytest

from mistsim.agents import archetypes
from mistsim.agents.synergy import RULES, synergy_score
from mistsim.agents.utility import make
from mistsim.domain.state import GameConfig, Mode
from mistsim.engine.game import GameEngine


def test_every_archetype_plays_a_full_game(content):
    for name in archetypes.names():
        engine = GameEngine(content=content,
                            config=GameConfig(num_players=2, max_turns=25), seed=4)
        result = engine.run([make(name, 1), make("equilibrado", 2)])
        assert result.reason, name


def test_archetypes_actually_buy_different_cards(content):
    """Si dos estrategias compran lo mismo, no son dos estrategias."""
    purchases = {}
    for name in ("aggro-combate", "rush-mision", "motor-riot", "rampa-economica"):
        engine = GameEngine(content=content,
                            config=GameConfig(num_players=2, max_turns=25), seed=21)
        result = engine.run([make(name, 1), make("equilibrado", 2)])
        purchases[name] = {e.data["card"] for e in result.log
                           if e.kind == "buy" and e.player == 0}

    assert all(purchases.values()), f"alguna estrategia no compró nada: {purchases}"
    for a, b in [("aggro-combate", "rush-mision"), ("motor-riot", "rampa-economica")]:
        overlap = purchases[a] & purchases[b]
        union = purchases[a] | purchases[b]
        assert len(overlap) / len(union) < 0.75, (
            f"{a} y {b} compran casi lo mismo: {overlap}")


def test_combat_strategy_deals_more_damage_than_mission_strategy(content):
    """La prueba de que un perfil se traduce en conducta, no sólo en pesos."""
    def damage_dealt(strategy):
        total = 0
        for seed in range(6):
            engine = GameEngine(content=content,
                                config=GameConfig(num_players=2, max_turns=20),
                                seed=seed)
            result = engine.run([make(strategy, 1), make("equilibrado", 2)])
            total += sum(e.data["amount"] for e in result.log
                         if e.kind == "damage" and e.data.get("by") == 0)
        return total

    assert damage_dealt("aggro-combate") > damage_dealt("rush-mision")


def test_mission_strategy_climbs_tracks_faster(content):
    def track_progress(strategy):
        total = 0
        for seed in range(6):
            engine = GameEngine(content=content,
                                config=GameConfig(num_players=2, max_turns=20),
                                seed=seed)
            result = engine.run([make(strategy, 1), make("equilibrado", 2)])
            total += sum(pos.get(0, 0) for pos in result.mission_positions.values())
        return total

    assert track_progress("rush-mision") > track_progress("aggro-combate")


# --- sinergias ---------------------------------------------------------------


def test_synergy_rewards_matching_boards_and_ignores_others(content):
    """Rebel escala con Aliados; Dominate no, porque quiere fuentes de misión."""
    allies = [content.market_by_name(n) for n in
              ("Soldier", "Pewterarm", "Coinshot", "Rioter")]
    rebel = content.market_by_name("Rebel")
    dominate = content.market_by_name("Dominate")

    assert synergy_score(rebel, allies) > 3.0
    assert synergy_score(dominate, allies) == 0.0

    mission_sources = [content.market_by_name(n) for n in
                       ("Pursue", "Unveil", "Sneak", "Infiltrate")]
    assert synergy_score(dominate, mission_sources) > 2.0


def test_confrontation_needs_atium_far_more_than_anything_else(content):
    """Confrontation gana con 4 Atium, así que la generación de Atium lo domina todo.

    No llega a 0 sin Atium: su primaria juega desde el montón de eliminadas, y las
    cartas que eliminan cosas (Con) lo alimentan. Esa sinergia menor es real, pero
    debe quedar muy por debajo de la que importa.
    """
    confrontation = content.market_by_name("Confrontation")
    no_atium = [content.market_by_name(n) for n in ("Strike", "Con", "Hunt")]
    atium = [content.market_by_name(n) for n in ("Balance", "Ruin", "Kandra")]

    assert synergy_score(confrontation, atium) >= 7.0
    assert synergy_score(confrontation, atium) > 4 * synergy_score(confrontation, no_atium)


def test_every_synergy_rule_can_fire_somewhere_in_the_market(content):
    """Una regla que nunca se dispara es una regla muerta."""
    cards = list(content.market)
    for rule in RULES:
        applies = [c for c in cards if rule.applies(c)]
        partners = [c for c in cards if rule.partner(c)]
        assert applies, f"ninguna carta activa la regla {rule.name}"
        assert partners, f"ninguna carta es pareja de la regla {rule.name}"


# --- comportamiento del agente ----------------------------------------------


def test_agent_prefers_the_option_its_profile_values(content):
    """Train in Secret ofrece elegir; cada estrategia debe coger lo suyo."""
    options = ["train:1", "combat:2", "mission:2", "heal:3"]
    assert make("aggro-combate").choose_option(options, "test") == "combat:2"
    assert make("rush-mision").choose_option(options, "test") == "mission:2"
    assert make("muro-defender").choose_option(options, "test") == "heal:3"


def test_agent_eliminates_its_worst_card_not_its_best(content):
    """Soothe debe adelgazar el mazo, no destruirlo."""
    from mistsim.domain.cards import CardInstance

    agent = make("adelgazar")
    junk = CardInstance(1, content.funding)
    gem = CardInstance(2, content.market_by_name("Ascendant"))
    assert agent.choose_card([junk, gem], "soothe") is junk
    assert agent.choose_card([junk, gem], "buy-eliminated") is gem


@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_coop_runs_for_every_player_count(content, players):
    engine = GameEngine(content=content,
                        config=GameConfig(mode=Mode.COOP, num_players=players,
                                          max_turns=30),
                        seed=9)
    result = engine.run([make("equilibrado", i) for i in range(players)])
    assert result.reason


def test_mission_victory_requires_the_same_player_to_top_all_three(content):
    """La victoria instantánea es coronar LAS TRES pistas, no una."""
    for seed in range(20):
        engine = GameEngine(content=content,
                            config=GameConfig(num_players=2, max_turns=40), seed=seed)
        result = engine.run([make("rush-mision", 1), make("rush-mision", 2)])
        if result.reason == "all-missions":
            winner = result.winner
            for track, positions in result.mission_positions.items():
                assert positions.get(winner) == 12, (track, positions)
            return
    pytest.skip("ninguna partida terminó por Misiones en las semillas probadas")
