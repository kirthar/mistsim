"""Log estructurado de eventos.

Todo lo que ocurre pasa por aquí. El CLI, los reportes y el futuro visor web sólo
consumen eventos, nunca hurgan en el estado; y la partida dorada de los tests compara
precisamente esta secuencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str
    turn: int
    player: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        who = f"P{self.player}" if self.player is not None else "--"
        bits = " ".join(f"{k}={v}" for k, v in self.data.items())
        return f"[T{self.turn:02d} {who}] {self.kind} {bits}".rstrip()


class EventLog:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.turn = 0

    def emit(self, kind: str, player: int | None = None, **data: Any) -> Event:
        event = Event(kind=kind, turn=self.turn, player=player, data=data)
        self.events.append(event)
        return event

    def of_kind(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)
