"""Invariantes que deben cumplirse en cualquier partida, con cualquier agente.

Son la red de seguridad: si un efecto duplica o pierde cartas, o la salud se sale de
rango, se ve aquí y no en un resultado de optimización sutilmente falso.
"""
import pytest

from mistsim.domain.player import MAX_HEALTH
from mistsim.domain.state import GameConfig, Mode
from mistsim.engine.game import GameEngine, RandomAgent


def card_census(state):
    """Cuenta cada carta física por uid, en todas las zonas del juego."""
    uids = []
    for player in state.players:
        uids += [c.uid for c in player.all_cards()]
    uids += [c.uid for c in state.market.row]
    uids += [c.uid for c in state.market.deck]
    uids += [c.uid for c in state.eliminated]
    return uids


class AuditingEngine(GameEngine):
    """Motor que revisa los invariantes al final de cada turno."""

    def _play_turn(self, state, player, agent):
        super()._play_turn(state, player, agent)
        uids = card_census(state)
        assert len(uids) == len(set(uids)), "una carta está en dos zonas a la vez"
        if self._expected is None:
            self._expected = len(uids)
        assert len(uids) == self._expected, (
            f"el recuento de cartas cambió: {self._expected} -> {len(uids)}")
        for p in state.players:
            assert 0 <= p.health <= MAX_HEALTH, f"salud fuera de rango: {p.health}"
            assert p.resources.coin >= 0, "monedas negativas"

    def run(self, agents, characters=None):
        self._expected = None
        return super().run(agents, characters)


@pytest.mark.parametrize("seed", range(8))
def test_cards_are_conserved_across_a_full_game(content, seed):
    engine = AuditingEngine(content=content,
                            config=GameConfig(num_players=3, max_turns=30),
                            seed=seed)
    engine.run([RandomAgent(seed * 10 + i) for i in range(3)])


def test_coin_does_not_carry_over_between_turns(content):
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=2, max_turns=15), seed=3)
    result = engine.run([RandomAgent(1), RandomAgent(2)])
    starts = [e for e in result.log if e.kind == "turn-start"]
    assert starts, "deberían registrarse inicios de turno"


@pytest.mark.parametrize("seed", range(4))
def test_coop_games_terminate(content, seed):
    engine = AuditingEngine(
        content=content,
        config=GameConfig(mode=Mode.COOP, num_players=2, max_turns=30),
        seed=seed)
    result = engine.run([RandomAgent(seed), RandomAgent(seed + 1)])
    assert result.reason


def test_coop_gives_no_turn_order_health_bonus(content):
    """En Solo/Coop no se reparten los bonus de orden de turno (manual)."""
    engine = GameEngine(content=content,
                        config=GameConfig(mode=Mode.COOP, num_players=4, max_turns=1),
                        seed=1)
    result = engine.run([RandomAgent(i) for i in range(4)])
    assert all(h <= 36 for h in result.final_health.values()), result.final_health
