"""El contenido debe cuadrar con el juego físico antes de simular nada."""
import pytest

from mistsim.content.loader import ContentError, load_content, validate
from mistsim.domain.cards import CardType


@pytest.fixture(scope="module")
def content():
    return load_content()


def test_market_has_65_names_and_82_physical_cards(content):
    assert len(content.market) == 65
    assert sum(c.copies for c in content.market) == 82


def test_card_numbers_are_unique_and_gaps_match_duplicate_cards(content):
    """Los 65 números impresos dejan 17 huecos, que son las 17 cartas de 2 copias."""
    numbers = [c.card_number for c in content.market]
    assert all(n is not None for n in numbers)
    assert len(set(numbers)) == 65
    gaps = set(range(1, 83)) - set(numbers)
    duplicates = [c for c in content.market if c.copies == 2]
    assert len(gaps) == len(duplicates) == 17


def test_every_ally_has_defense_and_no_action_does(content):
    for card in content.market:
        if card.type is CardType.ALLY:
            assert card.defense is not None, card.name
        else:
            assert card.defense is None, card.name


def test_secondary_requires_primary_and_costs_extra_burns(content):
    for card in content.market:
        if card.secondary:
            assert card.primary is not None, card.name
            assert card.secondary.extra_burns >= 1, card.name


def test_allies_are_never_usable_as_metal(content):
    """El FAQ: un Aliado nunca alimenta otra carta ni refresca un metal."""
    for card in content.market:
        if card.type is CardType.ALLY:
            assert card.playable_as_metal() == ()


def test_corrections_from_card_images_are_applied(content):
    """Guarda las correcciones de la Fase 0 para que nadie las revierta por accidente."""
    by_name = {c.name: c for c in content.market}

    # "+2 METAL" en la cabecera = 2 quemas adicionales, no 1.
    for name in ("Ascendant", "Dominate", "Maelstrom", "Crushing Blow",
                 "House War", "Hyperaware"):
        assert by_name[name].secondary.extra_burns == 2, name

    # El combate va dentro del glifo de espadas, no es el número del keyword.
    assert by_name["Assassinate"].primary.effects["combat"] == 3
    assert by_name["Crash"].primary.effects["combat"] == 2
    assert by_name["Rescue"].primary.effects["combat"] == 3
    assert by_name["Precise Shot"].primary.effects["combat"] == 3
    assert by_name["Lurcher"].primary.effects["combat"] == 2

    # Cuadrado = misión, no círculo = moneda.
    assert by_name["Lookout"].primary.effects == {"mission": 2}
    assert by_name["Steelpush"].secondary.effects == {"combat": 1, "mission": 2}

    assert "Cushing Blow" not in by_name
    assert by_name["Noble"].defense == 2
    assert by_name["Crash"].savant == {"combat": 2}


def test_all_five_characters_with_level_1_abilities(content):
    by_id = {c.id: c for c in content.characters}
    assert set(by_id) == {"vin", "kelsier", "shan", "marsh", "vin_brass"}
    assert by_id["vin"].level_1_effects == {"combat": 1, "heal": 1, "coin": 1}
    assert by_id["kelsier"].level_1_effects == {"combat": 2}
    assert by_id["shan"].level_1_effects == {"coin": 2}
    assert by_id["marsh"].level_1_effects == {"mission": 2}
    assert by_id["vin_brass"].level_1_effects == {"soothe": 1}
    assert by_id["vin_brass"].promo is True


def test_starter_deck_is_ten_cards_per_character(content):
    for char in content.characters:
        deck = content.starting_deck(char.id)
        assert len(deck) == 10, char.id
        assert sum(1 for c in deck if c.name == "Funding") == 6


def test_training_sets_cover_all_eight_metals_via_pairs(content):
    """4 cartas de Entrenamiento bastan porque cada una vale también como su pareja."""
    for char in content.characters:
        reachable = set()
        for card in content.starting_deck(char.id):
            reachable.update(card.playable_as_metal())
        assert len(reachable) == 8, (char.id, reachable)


def test_homebrew_content_is_flagged_as_unverified(content):
    """El motor debe poder decir siempre qué resultados descansan en datos inventados."""
    assert content.provenance["market_cards"] is True
    assert content.provenance["characters"] is True
    assert content.provenance["starter_deck"] is True
    assert content.provenance["missions"] is True
    # El mazo del Lord Ruler sigue sin transcribirse: es el único inventado que queda.
    assert content.provenance["lord_ruler"] is False


def test_all_eight_missions_come_from_the_photographed_cards(content):
    """Las 8 tienen datos reales; ninguna queda como reconstrucción."""
    assert len(content.missions) == 8
    assert all(m.verified for m in content.missions), [
        m.name for m in content.missions if not m.verified]


def test_mission_rewards_sit_on_the_track(content):
    """Casillas 1..11: la 12 es la cima, que tiene su propia recompensa aparte."""
    for mission in content.missions:
        posiciones = [r.position for r in mission.rewards]
        assert posiciones == sorted(posiciones), f"{mission.name}: fuera de orden"
        assert len(set(posiciones)) == len(posiciones), f"{mission.name}: repetidas"
        for p in posiciones:
            assert 1 <= p < 12, f"{mission.name}: casilla {p} fuera de la pista"


def test_every_mission_has_a_top_reward_and_a_first_player_bonus(content):
    for mission in content.missions:
        assert mission.top_reward, mission.name
        assert mission.top_reward_first_bonus, mission.name


def test_validate_rejects_a_short_market(content):
    with pytest.raises(ContentError, match="65 cartas"):
        validate(content.market[:-1], content.missions, {"cards": [{}] * 36})
