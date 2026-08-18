"""Cómo el motor pregunta por una decisión.

Algunos efectos exigen elegir (qué carta eliminar, qué opción de `choice_of`, a qué
Aliado matar). El motor no decide: pregunta a un `Chooser`, que implementa el agente.
Así la misma lógica de reglas sirve para la IA, para un humano y para el solver de turno
óptimo, sin duplicar el motor.
"""
from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class Chooser(Protocol):
    def choose_option(self, options: list[str], context: str) -> str:
        """Elige una de las opciones de un efecto `choice_of` (p.ej. "combat:3")."""

    def choose_card(self, candidates: list[T], context: str, optional: bool = False) -> T | None:
        """Elige una carta de una lista. Devuelve None sólo si `optional`."""

    def choose_player(self, candidates: list[int], context: str) -> int:
        """Elige un jugador objetivo."""

    def choose_amount(self, maximum: int, context: str) -> int:
        """Elige cuánto usar de un efecto con tope (p.ej. cuántas cartas mover con Pull)."""


class GreedyChooser:
    """Elección por defecto, determinista: la primera opción y el máximo permitido.

    Sirve de referencia en los tests y como respaldo cuando un agente no opina.
    """

    def choose_option(self, options: list[str], context: str) -> str:
        return options[0]

    def choose_card(self, candidates: list[T], context: str, optional: bool = False) -> T | None:
        return candidates[0] if candidates else None

    def choose_player(self, candidates: list[int], context: str) -> int:
        return candidates[0]

    def choose_amount(self, maximum: int, context: str) -> int:
        return maximum
