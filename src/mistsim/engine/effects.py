"""Registro de efectos: clave del JSON -> función que la resuelve.

Las cartas del Mercado usan 41 claves distintas. Modelarlas como un registro en vez de
como un if gigante es lo que permite que añadir una carta sea tocar `data/` y no el
motor. Una clave desconocida revienta en modo estricto, en vez de resolverse a nada
en silencio y falsear una simulación.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mistsim.domain.cards import Effects
from mistsim.domain.player import Player
from mistsim.domain.state import GameState
from mistsim.engine.choices import Chooser
from mistsim.engine.events import EventLog


class UnknownEffect(Exception):
    """La carta pide un efecto que el motor no sabe resolver."""


@dataclass
class EffectContext:
    state: GameState
    player: Player
    log: EventLog
    chooser: Chooser
    source: str = "?"
    #: Efectos pendientes que sólo pueden resolverse al final del turno.
    deferred: list[tuple[str, Any]] = field(default_factory=list)
    #: Cartas ya usadas por un Seek en la cadena actual.
    #:
    #: Seek resuelve la primaria de una carta del Mercado, y esa carta puede tener a su
    #: vez un Seek: con sólo 6 cartas en la fila, la cadena se muerde la cola y recursa
    #: sin fin. Las reglas no contemplan ese bucle porque nadie lo jugaría, pero el
    #: motor sí necesita cerrarlo: una carta no puede volver a ser objetivo dentro de
    #: la misma cadena.
    seek_chain: frozenset[str] = frozenset()

    @property
    def res(self):
        return self.player.resources


EffectFn = Callable[[EffectContext, Any], None]
REGISTRY: dict[str, EffectFn] = {}


def effect(*keys: str) -> Callable[[EffectFn], EffectFn]:
    def register(fn: EffectFn) -> EffectFn:
        for key in keys:
            REGISTRY[key] = fn
        return fn
    return register


def resolve(effects: Effects, ctx: EffectContext, *, strict: bool = True) -> None:
    """Resuelve un bloque de efectos en orden.

    El orden importa de verdad: el FAQ dice que los efectos se activan de inmediato al
    alimentar la carta, así que `House War` y `Dominate` sólo convierten lo acumulado
    hasta ese momento, no lo que llegue después.
    """
    for key, value in effects.items():
        fn = REGISTRY.get(key)
        if fn is None:
            if strict:
                raise UnknownEffect(f"{ctx.source}: efecto desconocido {key!r}")
            ctx.log.emit("effect-skipped", ctx.player.id, effect=key, source=ctx.source)
            continue
        fn(ctx, value)


# --- acumuladores simples ----------------------------------------------------

@effect("coin")
def _coin(ctx: EffectContext, value: int) -> None:
    ctx.res.coin += value


@effect("combat")
def _combat(ctx: EffectContext, value: int) -> None:
    ctx.res.combat += value


@effect("mission")
def _mission(ctx: EffectContext, value: int) -> None:
    # El acumulador puede bajar con efectos negativos, pero nunca por debajo de 0;
    # la posición en la pista jamás retrocede (FAQ).
    ctx.res.mission = max(0, ctx.res.mission + value)


@effect("heal")
def _heal(ctx: EffectContext, value: int) -> None:
    healed = ctx.player.heal(value)
    if healed:
        ctx.log.emit("heal", ctx.player.id, amount=healed, source=ctx.source)


@effect("draw")
def _draw(ctx: EffectContext, value: int) -> None:
    drawn = ctx.player.draw(value, ctx.state.rng)
    ctx.log.emit("draw", ctx.player.id, count=len(drawn), source=ctx.source)


@effect("train")
def _train(ctx: EffectContext, value: int) -> None:
    moved = ctx.player.advance_training(value)
    if moved:
        ctx.log.emit("train", ctx.player.id, steps=moved, total=ctx.player.training)


@effect("atium")
def _atium(ctx: EffectContext, value: int) -> None:
    ctx.player.atium += value


# --- keywords ----------------------------------------------------------------

@effect("pull")
def _pull(ctx: EffectContext, value: int) -> None:
    """Iron: mueve cartas del descarte al tope del mazo. No las roba."""
    player = ctx.player
    limit = min(value, len(player.discard))
    if limit <= 0:
        return
    count = ctx.chooser.choose_amount(limit, f"pull ({ctx.source})")
    for _ in range(count):
        chosen = ctx.chooser.choose_card(player.discard, f"pull ({ctx.source})")
        if chosen is None:
            break
        player.discard.remove(chosen)
        player.deck.append(chosen)
    ctx.log.emit("pull", player.id, count=count, source=ctx.source)


@effect("push")
def _push(ctx: EffectContext, value: int) -> None:
    """Steel: elimina cartas del Mercado; se reponen de inmediato."""
    for _ in range(value):
        if not ctx.state.market.row:
            break
        chosen = ctx.chooser.choose_card(ctx.state.market.row, f"push ({ctx.source})")
        if chosen is None:
            break
        ctx.state.market.take(chosen)
        ctx.state.eliminated.append(chosen)
        ctx.log.emit("push", ctx.player.id, card=chosen.name, source=ctx.source)


@effect("soothe")
def _soothe(ctx: EffectContext, value: int) -> None:
    """Brass: elimina cartas propias de mano, descarte o juego. Adelgaza el mazo."""
    player = ctx.player
    for _ in range(value):
        pool = [*player.hand, *player.discard, *player.in_play]
        if not pool:
            break
        chosen = ctx.chooser.choose_card(pool, f"soothe ({ctx.source})", optional=True)
        if chosen is None:
            break
        for zone in (player.hand, player.discard, player.in_play):
            if chosen in zone:
                zone.remove(chosen)
                break
        ctx.state.eliminated.append(chosen)
        ctx.log.emit("soothe", player.id, card=chosen.name, source=ctx.source)


@effect("sense")
def _sense(ctx: EffectContext, value: int) -> None:
    """Tin: impide a los rivales avanzar en una pista el resto del turno.

    No hace nada contra el Lord Ruler (FAQ).
    """
    if ctx.state.lord_ruler and not ctx.state.config.sense_affects_lord_ruler:
        ctx.log.emit("sense-noop", ctx.player.id, reason="lord-ruler", source=ctx.source)
    for track in ctx.state.tracks:
        for opponent in ctx.state.opponents(ctx.player.id):
            track.sensed.add(opponent.id)
    ctx.log.emit("sense", ctx.player.id, value=value, source=ctx.source)


@effect("cloud")
def _cloud(ctx: EffectContext, value: int) -> None:
    """Copper: reduce daño entrante. Se juega fuera de turno, así que se difiere."""
    ctx.deferred.append(("cloud", value))


@effect("cloud_protect_ally")
def _cloud_protect_ally(ctx: EffectContext, value: Any) -> None:
    ctx.deferred.append(("cloud_protect_ally", True))


@effect("seek")
def _seek(ctx: EffectContext, value: int) -> None:
    """Bronze: usa la habilidad primaria de una Acción del Mercado sin comprarla.

    Nunca alcanza la secundaria, y no exige quemar el metal de la carta objetivo:
    basta el Bronce que activó el Seek (FAQ).
    """
    candidates = _seek_targets(ctx, value)
    if not candidates:
        ctx.log.emit("seek-empty", ctx.player.id, limit=value, source=ctx.source)
        return
    chosen = ctx.chooser.choose_card(candidates, f"seek<={value}")
    if chosen is None:
        return
    ctx.log.emit("seek", ctx.player.id, card=chosen.name, limit=value, source=ctx.source)
    resolve(chosen.card.primary.effects, _seek_context(ctx, chosen))


def _seek_targets(ctx: EffectContext, limit: int, exclude: frozenset[str] = frozenset()):
    """Acciones del Mercado alcanzables por un Seek de este límite de coste.

    Seek nunca llega a la habilidad secundaria de su objetivo, sólo a la primaria.
    """
    return [
        inst for inst in ctx.state.market.row
        if not inst.card.is_ally and inst.card.cost <= limit and inst.card.primary
        and inst.name not in ctx.seek_chain and inst.name not in exclude
    ]


def _seek_context(ctx: EffectContext, target) -> EffectContext:
    return EffectContext(
        ctx.state, ctx.player, ctx.log, ctx.chooser,
        source=f"seek:{target.name}", deferred=ctx.deferred,
        seek_chain=ctx.seek_chain | {target.name},
    )


@effect("seek_two_different_cards")
def _seek_two(ctx: EffectContext, value: int) -> None:
    seen: set[str] = set()
    for _ in range(2):
        candidates = _seek_targets(ctx, value, exclude=frozenset(seen))
        if not candidates:
            break
        chosen = ctx.chooser.choose_card(candidates, f"seek<={value}")
        if chosen is None:
            break
        seen.add(chosen.name)
        resolve(chosen.card.primary.effects, _seek_context(ctx, chosen))


@effect("riot")
def _riot(ctx: EffectContext, value: int) -> None:
    """Zinc: activa la primaria de un Aliado sin quemar su metal.

    Por la errata del FAQ, Riot es una activación *extra*: no bloquea ni sustituye a la
    normal por quema. De ahí que la vía se registre por separado.
    """
    player = ctx.player
    for _ in range(value):
        candidates = [
            a for a in player.allies
            if a.card.primary and "riot" not in a.activations_used
        ]
        if not candidates:
            break
        chosen = ctx.chooser.choose_card(candidates, "riot", optional=True)
        if chosen is None:
            break
        # Marcar ANTES de resolver: si el Aliado activado tiene a su vez Riot, no
        # puede volver a elegirse a sí mismo y la cadena queda acotada.
        chosen.activations_used.add("riot")
        ctx.log.emit("riot", player.id, ally=chosen.name, source=ctx.source)
        inner = EffectContext(ctx.state, player, ctx.log, ctx.chooser,
                              source=f"riot:{chosen.name}", deferred=ctx.deferred,
                              seek_chain=ctx.seek_chain)
        resolve(chosen.card.primary.effects, inner)


# --- conversiones ------------------------------------------------------------

@effect("convert_all_mission_to_combat")
def _mission_to_combat(ctx: EffectContext, value: Any) -> None:
    amount = ctx.res.mission
    ctx.res.mission = 0
    ctx.res.combat += amount
    ctx.log.emit("convert", ctx.player.id, frm="mission", to="combat", amount=amount)


@effect("convert_all_combat_to_mission")
def _combat_to_mission(ctx: EffectContext, value: Any) -> None:
    amount = ctx.res.combat
    ctx.res.combat = 0
    ctx.res.mission += amount
    ctx.log.emit("convert", ctx.player.id, frm="combat", to="mission", amount=amount)


# --- efectos que dependen de la posición en las pistas -----------------------

def _tracks_where(ctx: EffectContext, highest: bool) -> int:
    ids = ctx.state.alive_ids()
    test = "is_highest" if highest else "is_lowest"
    return sum(1 for t in ctx.state.tracks if getattr(t, test)(ctx.player.id, ids))


@effect("combat_per_highest_mission_track")
def _combat_per_highest(ctx: EffectContext, value: int) -> None:
    ctx.res.combat += value * _tracks_where(ctx, highest=True)


@effect("coin_per_lowest_mission_track")
def _coin_per_lowest(ctx: EffectContext, value: int) -> None:
    ctx.res.coin += value * _tracks_where(ctx, highest=False)


@effect("draw_per_highest_mission_track")
def _draw_per_highest(ctx: EffectContext, value: int) -> None:
    count = value * _tracks_where(ctx, highest=True)
    if count:
        ctx.player.draw(count, ctx.state.rng)


@effect("draw_if_lowest_on_any_mission_track")
def _draw_if_lowest(ctx: EffectContext, value: int) -> None:
    if _tracks_where(ctx, highest=False) > 0:
        ctx.player.draw(value, ctx.state.rng)


@effect("advance_mission_track_if_lowest_all")
def _advance_if_lowest(ctx: EffectContext, value: int) -> None:
    """Eavesdrop: sube en cada Misión en la que seas el más bajo."""
    ids = ctx.state.alive_ids()
    for track in ctx.state.tracks:
        if track.is_lowest(ctx.player.id, ids) and ctx.player.id not in track.sensed:
            track.positions[ctx.player.id] = track.position_of(ctx.player.id) + value
            ctx.log.emit("mission-advance", ctx.player.id, track=track.mission.name,
                         to=track.positions[ctx.player.id], source=ctx.source)
