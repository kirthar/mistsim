import random

import pytest

from mistsim.content.loader import load_content
from mistsim.domain.state import GameConfig
from mistsim.engine.events import EventLog
from mistsim.engine.setup import new_game


@pytest.fixture(scope="session")
def content():
    return load_content()


@pytest.fixture
def log():
    return EventLog()


@pytest.fixture
def game(content, log):
    """Partida PvP a 2 con semilla fija."""
    config = GameConfig(num_players=2, max_turns=40)
    return new_game(content, config, ["vin", "kelsier"], random.Random(7), log)
