"""Efectos de carta únicos: los que sólo aparecen en una o dos cartas.

Separados de effects.py para que el núcleo (acumuladores y keywords) se lea de un
vistazo. Importar este módulo los registra.
"""
from __future__ import annotations

from typing import Any

from mistsim.engine.effects import EffectContext, effect, resolve, unimplemented

# --- matar Aliados -----------------------------------------------------------


@effect("kill_ally")
def _kill_ally(ctx: EffectContext, value: int) -> None:
    """Mata Aliados rivales directamente, sin gastar combate."""
    for _ in range(value):
        targets = [(p, a) for p in ctx.state.opponents(ctx.player.id) for a in p.allies]
        if not targets:
            break
        # Los Defender protegen al resto igual que en combate.
        defenders = [t for t in targets if t[1].card.is_defender]
        pool = defenders or targets
        chosen = ctx.chooser.choose_card([a for _, a in pool], f"kill_ally ({ctx.source})")
        if chosen is None:
            break
        owner = next(p for p, a in pool if a is chosen)
        owner.allies.remove(chosen)
        owner.discard.append(chosen)
        ctx.log.emit("ally-killed", owner.id, ally=chosen.name, by=ctx.player.id,
                     source=ctx.source)


@effect("kill_all_opponent_allies")
def _kill_all_allies(ctx: EffectContext, value: Any) -> None:
    for opponent in ctx.state.opponents(ctx.player.id):
        for ally in list(opponent.allies):
            opponent.allies.remove(ally)
            opponent.discard.append(ally)
            ctx.log.emit("ally-killed", opponent.id, ally=ally.name, by=ctx.player.id,
                         source=ctx.source)
    # En Coop, "derrota a todos los Aliados rivales" tumba todos los escudos (FAQ).
    if ctx.state.lord_ruler:
        for adv_id in list(ctx.state.lord_ruler.shields):
            ctx.state.lord_ruler.shields[adv_id] = []
            ctx.log.emit("shields-destroyed", ctx.player.id, adversary=adv_id,
                         source=ctx.source)


# --- manipulación del Mercado ------------------------------------------------


@effect("eliminate_all_market_cards")
def _wipe_market(ctx: EffectContext, value: Any) -> None:
    for inst in list(ctx.state.market.row):
        ctx.state.market.row.remove(inst)
        ctx.state.eliminated.append(inst)
    ctx.state.market.refill()
    ctx.log.emit("market-wiped", ctx.player.id, source=ctx.source)


@effect("gain_market_card_to_discard_max_cost")
def _gain_market_card(ctx: EffectContext, value: int) -> None:
    candidates = [i for i in ctx.state.market.row if i.card.cost <= value]
    if not candidates:
        return
    chosen = ctx.chooser.choose_card(candidates, f"gain<={value}", optional=True)
    if chosen is None:
        return
    ctx.state.market.take(chosen)
    ctx.player.discard.append(chosen)
    ctx.log.emit("gain", ctx.player.id, card=chosen.name, to="discard", source=ctx.source)


# --- el montón de eliminadas -------------------------------------------------


def _take_eliminated(ctx: EffectContext, destination: str) -> None:
    if not ctx.state.eliminated:
        return
    chosen = ctx.chooser.choose_card(ctx.state.eliminated, "from-eliminated", optional=True)
    if chosen is None:
        return
    ctx.state.eliminated.remove(chosen)
    target = ctx.player.hand if destination == "hand" else ctx.player.discard
    target.append(chosen)
    ctx.log.emit("recover", ctx.player.id, card=chosen.name, to=destination,
                 source=ctx.source)


@effect("gain_eliminated_card_to_discard")
def _gain_elim_discard(ctx: EffectContext, value: int) -> None:
    _take_eliminated(ctx, "discard")


@effect("gain_eliminated_card_to_hand")
def _gain_elim_hand(ctx: EffectContext, value: int) -> None:
    _take_eliminated(ctx, "hand")


@effect("may_buy_eliminated_card")
def _may_buy_eliminated(ctx: EffectContext, value: Any) -> None:
    """Soar: deja comprar del montón de eliminadas, pagando su coste."""
    affordable = [i for i in ctx.state.eliminated if i.card.cost <= ctx.res.coin]
    if not affordable:
        return
    chosen = ctx.chooser.choose_card(affordable, "buy-eliminated", optional=True)
    if chosen is None:
        return
    ctx.res.coin -= chosen.card.cost
    ctx.state.eliminated.remove(chosen)
    ctx.player.discard.append(chosen)
    ctx.log.emit("buy", ctx.player.id, card=chosen.name, source="eliminated-pile")


@effect("play_top_ability_of_eliminated_card")
def _play_eliminated(ctx: EffectContext, value: int) -> None:
    """Confrontation: resuelve la primaria de una carta eliminada sin recuperarla."""
    candidates = [i for i in ctx.state.eliminated if i.card.primary]
    if not candidates:
        return
    chosen = ctx.chooser.choose_card(candidates, "play-eliminated")
    if chosen is None:
        return
    ctx.log.emit("play-eliminated", ctx.player.id, card=chosen.name, source=ctx.source)
    inner = EffectContext(ctx.state, ctx.player, ctx.log, ctx.chooser,
                          source=f"eliminated:{chosen.name}", deferred=ctx.deferred)
    resolve(chosen.card.primary.effects, inner)


# --- mazo propio -------------------------------------------------------------


@effect("look_top_deck_eliminate_or_return")
def _peek_top(ctx: EffectContext, value: int) -> None:
    """Informant: mira el tope del mazo y decide si eliminarlo. Adelgaza sin gastar Soothe."""
    player = ctx.player
    if not player.deck:
        player.draw(0, ctx.state.rng)
    if not player.deck:
        return
    top = player.deck[-1]
    keep = ctx.chooser.choose_card([top], "eliminate-top?", optional=True)
    if keep is not None:
        player.deck.pop()
        ctx.state.eliminated.append(top)
        ctx.log.emit("eliminate-top", player.id, card=top.name, source=ctx.source)


@effect("set_aside_hand_card_draw_next_turn")
def _set_aside(ctx: EffectContext, value: int) -> None:
    """Keeper: guarda una carta de la mano; se roba al empezar el turno siguiente."""
    player = ctx.player
    if not player.hand:
        return
    chosen = ctx.chooser.choose_card(player.hand, "set-aside", optional=True)
    if chosen is None:
        return
    player.hand.remove(chosen)
    player.set_aside.append(chosen)
    ctx.log.emit("set-aside", player.id, card=chosen.name, source=ctx.source)


# --- elecciones --------------------------------------------------------------


def _apply_option(ctx: EffectContext, option: str) -> None:
    """Aplica una opción con formato "clave:valor" (p.ej. "combat:3")."""
    key, _, raw = option.partition(":")
    resolve({key: int(raw) if raw else 1}, ctx)


@effect("choice_of")
def _choice_of(ctx: EffectContext, options: list[str]) -> None:
    chosen = ctx.chooser.choose_option(list(options), f"choice ({ctx.source})")
    ctx.log.emit("choice", ctx.player.id, picked=chosen, source=ctx.source)
    _apply_option(ctx, chosen)


@effect("combat_or_coin_choice")
def _combat_or_coin(ctx: EffectContext, value: int) -> None:
    options = [f"combat:{value}", f"coin:{value}"]
    chosen = ctx.chooser.choose_option(options, f"choice ({ctx.source})")
    _apply_option(ctx, chosen)


# --- metales -----------------------------------------------------------------


@effect("refresh_any_flared_metal", "refresh_metal")
def _refresh_metal(ctx: EffectContext, value: Any) -> None:
    count = 1 if value is True else int(value)
    for _ in range(count):
        flared = ctx.player.tokens.flared()
        if not flared:
            break
        metal = flared[0]
        ctx.player.tokens.refresh(metal)
        ctx.log.emit("refresh", ctx.player.id, metal=str(metal), source=ctx.source)


# --- repetición y victoria ---------------------------------------------------


@effect("repeat_own_top_ability")
def _repeat_top(ctx: EffectContext, value: Any) -> None:
    """Seeker: repite la primaria de la misma Acción que acaba de usar su Seek.

    SIN IMPLEMENTAR: requiere recordar cuál fue el último objetivo de Seek dentro de la
    cadena, que hoy no se guarda. Se registra el hueco en vez de callarlo: un efecto que
    no hace nada en silencio es indistinguible de uno que funciona, y así al menos sale
    en el log y en el recuento de `effect-unimplemented`.
    """
    unimplemented(ctx, "repeat_own_top_ability")


@effect("win_game")
def _win(ctx: EffectContext, value: Any) -> None:
    ctx.state.winner = ctx.player.id
    ctx.state.victory_reason = "confrontation"
    ctx.state.finished = True
    ctx.log.emit("victory", ctx.player.id, reason="confrontation")


# --- recompensas de Misión y efectos del Lord Ruler --------------------------


def _grant_permanent(ctx: EffectContext, key: str, value: int) -> None:
    """Recompensa permanente de Misión: se acumula en `player.permanents`.

    `turn.start_turn` lee `permanents["coin"]` y `turn.end_turn` lee
    `permanents["draw"]`, así que basta con escribirlo aquí.
    """
    ctx.player.permanents[key] = ctx.player.permanents.get(key, 0) + value
    ctx.log.emit("permanent-gained", ctx.player.id, effect=key, value=value,
                 total=ctx.player.permanents[key], source=ctx.source)


@effect("permanent_coin_per_turn")
def _perm_coin(ctx: EffectContext, value: int) -> None:
    _grant_permanent(ctx, "coin", value)


@effect("permanent_draw_per_turn")
def _perm_draw(ctx: EffectContext, value: int) -> None:
    _grant_permanent(ctx, "draw", value)


@effect("permanent_refresh_per_turn")
def _perm_refresh(ctx: EffectContext, value: int) -> None:
    _grant_permanent(ctx, "refresh", value)


@effect("permanent_combat_per_turn")
def _perm_combat(ctx: EffectContext, value: int) -> None:
    """Guarnició de Luthadel: +N de combate al empezar cada turno, para siempre."""
    _grant_permanent(ctx, "combat", value)


@effect("permanent_burn_per_turn")
def _perm_burn(ctx: EffectContext, value: int) -> None:
    """Cavernes Skaa: +N al límite de quemas, para siempre.

    No es un recurso que se cobre cada turno sino una subida del límite, así que se
    concede una vez y `recompute_burn_limit` lo suma por encima de la pista de
    Entrenamiento y de los Aliados.
    """
    _grant_permanent(ctx, "burn", value)
    ctx.player.recompute_burn_limit()
    ctx.log.emit("burn-limit", ctx.player.id, limit=ctx.player.tokens.burn_limit,
                 source=ctx.source)


@effect("refresh_all")
def _refresh_all(ctx: EffectContext, value: Any) -> None:
    """Bonus de primer jugador de Cavernes Skaa: desflarea todos los metales."""
    for metal in ctx.player.tokens.flared():
        ctx.player.tokens.refresh(metal)
        ctx.log.emit("refresh", ctx.player.id, metal=str(metal), source=ctx.source)


@effect("destroy_adversary_shield")
def _destroy_shield(ctx: EffectContext, value: int) -> None:
    lr = ctx.state.lord_ruler
    if not lr:
        return
    for _ in range(value):
        for adv_id, shields in lr.shields.items():
            if shields:
                shields.pop(0)
                ctx.log.emit("shield-destroyed", ctx.player.id, adversary=adv_id,
                             source=ctx.source)
                break


@effect("damage")
def _damage(ctx: EffectContext, value: int) -> None:
    """Daño del Lord Ruler al jugador al que se dirige."""
    ctx.player.take_damage(value)
    ctx.log.emit("damage", ctx.player.id, amount=value, source=ctx.source)


@effect("coin_penalty")
def _coin_penalty(ctx: EffectContext, value: int) -> None:
    ctx.res.coin = max(0, ctx.res.coin - value)


@effect("mission_penalty")
def _mission_penalty(ctx: EffectContext, value: int) -> None:
    ctx.res.mission = max(0, ctx.res.mission - value)


@effect("draw_penalty", "discard_penalty")
def _discard_penalty(ctx: EffectContext, value: int) -> None:
    for _ in range(value):
        if not ctx.player.hand:
            break
        chosen = ctx.chooser.choose_card(ctx.player.hand, "forced-discard")
        if chosen is None:
            break
        ctx.player.hand.remove(chosen)
        ctx.player.discard.append(chosen)


@effect("eliminate_from_hand")
def _eliminate_from_hand(ctx: EffectContext, value: int) -> None:
    for _ in range(value):
        if not ctx.player.hand:
            break
        chosen = ctx.chooser.choose_card(ctx.player.hand, "forced-eliminate")
        if chosen is None:
            break
        ctx.player.hand.remove(chosen)
        ctx.state.eliminated.append(chosen)


@effect("burn_limit_penalty")
def _burn_penalty(ctx: EffectContext, value: int) -> None:
    ctx.player.burn_limit_penalty += value
    ctx.player.recompute_burn_limit()


@effect("collective_damage")
def _collective_damage_fallback(ctx: EffectContext, value: Any) -> None:
    """El daño colectivo lo reparte `lord_ruler._resolve_edict` antes de llamar aquí.

    Este resolutor sólo se alcanza si un Adversario lo lleva, que hoy no ocurre.
    """
    unimplemented(ctx, "collective_damage")


@effect("block_ally_activation", "block_seek", "block_pull", "block_sense",
        "block_market_buy_above")
def _blocking_penalty(ctx: EffectContext, value: Any) -> None:
    """SIN IMPLEMENTAR: penalizaciones permanentes de Adversario.

    `lord_ruler.permanent_penalties()` las recopila, pero `legal_actions` todavía no las
    consulta, así que un Adversario que debería bloquear Seek o Pull no bloquea nada.
    """
    unimplemented(ctx, str(value) if isinstance(value, str) else "block_*")
