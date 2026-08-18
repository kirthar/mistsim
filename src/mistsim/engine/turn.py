"""Ejecución de acciones y ciclo de turno."""
from __future__ import annotations

from mistsim.domain.cards import Ability, CardInstance
from mistsim.domain.missions import TRACK_LENGTH
from mistsim.domain.player import HAND_SIZE, Player
from mistsim.domain.state import GameState
from mistsim.engine.actions import Action, ActionKind
from mistsim.engine.choices import Chooser
from mistsim.engine.effects import EffectContext, resolve
from mistsim.engine.events import EventLog

BOXING_COST = 2
BOXING_VALUE = 1


class IllegalAction(Exception):
    pass


def _ctx(state: GameState, log: EventLog, chooser: Chooser, source: str) -> EffectContext:
    return EffectContext(state, state.player(state.active), log, chooser, source=source)


def apply(state: GameState, action: Action, log: EventLog, chooser: Chooser) -> None:
    """Aplica una acción legal al estado."""
    player = state.player(state.active)
    handler = _HANDLERS.get(action.kind)
    if handler is None:
        raise IllegalAction(f"acción no soportada: {action.kind}")
    handler(state, player, action, log, chooser)


# --- manejadores -------------------------------------------------------------


def _play_card(state, player, action, log, chooser):
    inst = action.card
    if inst not in player.hand:
        raise IllegalAction(f"{inst.name} no está en la mano")
    player.hand.remove(inst)
    if inst.card.is_ally:
        player.allies.append(inst)
        log.emit("ally-played", player.id, ally=inst.name)
        if inst.card.ongoing == "extra_metal_burn":
            player.tokens.burn_limit += 1
    else:
        player.in_play.append(inst)
        log.emit("card-played", player.id, card=inst.name)


def _burn(state, player, action, log, chooser):
    player.tokens.burn(action.metal)
    count = player.note_metal(action.metal)
    log.emit("burn", player.id, metal=str(action.metal), times=count)


def _flare(state, player, action, log, chooser):
    """Flarear cuenta como quemar para todo lo que se dispare con ese metal."""
    player.tokens.flare(action.metal)
    count = player.note_metal(action.metal)
    log.emit("flare", player.id, metal=str(action.metal), times=count)


def _card_as_metal(state, player, action, log, chooser):
    """Jugar una carta de lado. No consume quema de ficha y no tiene tope por turno."""
    inst = action.card
    if inst not in player.hand:
        raise IllegalAction(f"{inst.name} no está en la mano")
    player.hand.remove(inst)
    player.in_play.append(inst)
    count = player.note_metal(action.metal)
    log.emit("card-as-metal", player.id, card=inst.name, metal=str(action.metal), times=count)

    # El savant sólo se aplica jugando la carta ASÍ, nunca al jugarla normal.
    if inst.card.savant:
        ctx = _ctx(state, log, chooser, f"savant:{inst.name}")
        resolve(inst.card.savant, ctx)
        log.emit("savant", player.id, card=inst.name, effects=dict(inst.card.savant))


def _refresh(state, player, action, log, chooser):
    """Descarta una carta que case con el metal flareado para desflarearlo.

    Refrescar NO cuenta como quemar, así que no dispara Aliados ni personaje, y la
    ficha queda inutilizable el resto del turno (FAQ).
    """
    inst = action.payment
    if inst not in player.hand:
        raise IllegalAction(f"{inst.name} no está en la mano")
    player.hand.remove(inst)
    player.discard.append(inst)
    player.tokens.refresh(action.metal)
    log.emit("refresh", player.id, metal=str(action.metal), paid=inst.name)


def _activate_ability(state, player, inst: CardInstance, ability: Ability, tier: str,
                      log: EventLog, chooser: Chooser) -> None:
    ctx = _ctx(state, log, chooser, f"{inst.name}:{tier}")
    log.emit("activate", player.id, card=inst.name, tier=tier,
             metal=str(ability.metal) if ability.metal else None)
    resolve(ability.effects, ctx)
    if tier == "primary":
        inst.primary_activated = True
        inst.activations_used.add("burn")
    else:
        inst.activations_used.add("secondary")


def _activate(state, player, action, log, chooser):
    inst = action.card
    ability = inst.card.primary if action.tier == "primary" else inst.card.secondary
    if ability is None:
        raise IllegalAction(f"{inst.name} no tiene habilidad {action.tier}")
    if action.tier == "secondary" and not inst.primary_activated:
        raise IllegalAction(f"{inst.name}: la secundaria exige activar antes la primaria")
    _activate_ability(state, player, inst, ability, action.tier, log, chooser)


def _character(state, player, action, log, chooser):
    """Habilidad de Nivel I: una vez por turno, por muchas veces que se queme el metal."""
    if "character" in player.used_once_per_turn:
        raise IllegalAction("la habilidad de personaje ya se usó este turno")
    player.used_once_per_turn.add("character")
    ctx = _ctx(state, log, chooser, f"character:{player.character.id}")
    log.emit("character-ability", player.id, character=player.character.id,
             metal=player.character.signature_metal)
    resolve(player.character.level_1_effects, ctx)


def _buy(state, player, action, log, chooser):
    inst = action.card
    cost = inst.card.cost
    if cost > player.resources.coin:
        raise IllegalAction(f"no alcanza para {inst.name}")
    player.resources.coin -= cost
    state.market.take(inst)
    player.discard.append(inst)
    log.emit("buy", player.id, card=inst.name, cost=cost, coin_left=player.resources.coin)


def _buy_boxing(state, player, action, log, chooser):
    if player.resources.coin < BOXING_COST:
        raise IllegalAction("no alcanza para un Boxing")
    player.resources.coin -= BOXING_COST
    player.boxings += 1


def _sell_boxing(state, player, action, log, chooser):
    if player.boxings <= 0:
        raise IllegalAction("no hay Boxings que vender")
    player.boxings -= 1
    player.resources.coin += BOXING_VALUE


def _advance_mission(state, player, action, log, chooser):
    track = state.tracks[action.track]
    if player.id in track.sensed:
        raise IllegalAction(f"Sense bloquea a P{player.id} en {track.mission.name}")
    amount = min(action.amount, player.resources.mission)
    if amount <= 0:
        raise IllegalAction("no hay puntos de misión que gastar")
    player.resources.mission -= amount
    before = track.position_of(player.id)
    after = min(TRACK_LENGTH, before + amount)
    track.positions[player.id] = after
    log.emit("mission-advance", player.id, track=track.mission.name,
             frm=before, to=after, spent=amount)
    _claim_mission_rewards(state, player, track, before, after, log, chooser)


def _claim_mission_rewards(state, player, track, before, after, log, chooser):
    """Cobra las recompensas cruzadas, y el bonus de primer jugador si nadie lo tenía."""
    for reward in track.mission.rewards:
        if not (before < reward.position <= after):
            continue
        key = (player.id, reward.position)
        if key in track.claimed:
            continue
        track.claimed.add(key)
        ctx = _ctx(state, log, chooser, f"mission:{track.mission.name}@{reward.position}")
        resolve(reward.effects, ctx)
        log.emit("mission-reward", player.id, track=track.mission.name,
                 position=reward.position, effects=dict(reward.effects))
        if reward.first_player_bonus and reward.position not in track.first_claimed:
            track.first_claimed.add(reward.position)
            resolve(reward.first_player_bonus, ctx)
            log.emit("mission-first-bonus", player.id, track=track.mission.name,
                     position=reward.position)

    if after >= TRACK_LENGTH and track.finisher is None:
        track.finisher = player.id
        ctx = _ctx(state, log, chooser, f"mission-top:{track.mission.name}")
        if track.mission.top_reward:
            resolve(track.mission.top_reward, ctx)
        if track.mission.top_reward_first_bonus:
            resolve(track.mission.top_reward_first_bonus, ctx)
        log.emit("mission-completed", player.id, track=track.mission.name)


def _end_turn(state, player, action, log, chooser):
    pass  # el cierre lo lleva end_turn(), tras la fase de combate


_HANDLERS = {
    ActionKind.PLAY_CARD: _play_card,
    ActionKind.BURN: _burn,
    ActionKind.FLARE: _flare,
    ActionKind.CARD_AS_METAL: _card_as_metal,
    ActionKind.REFRESH: _refresh,
    ActionKind.ACTIVATE: _activate,
    ActionKind.ACTIVATE_ALLY: _activate,
    ActionKind.CHARACTER: _character,
    ActionKind.BUY: _buy,
    ActionKind.BUY_BOXING: _buy_boxing,
    ActionKind.SELL_BOXING: _sell_boxing,
    ActionKind.ADVANCE_MISSION: _advance_mission,
    ActionKind.END_TURN: _end_turn,
}


# --- estructura del turno ----------------------------------------------------


def start_turn(state: GameState, player: Player, log: EventLog) -> None:
    """Paso 1: avanzar la pista de Entrenamiento y aplicar lo permanente."""
    player.start_turn()
    moved = player.advance_training()
    log.emit("turn-start", player.id, training=player.training, health=player.health)
    if moved:
        _apply_training_rewards(player, log)

    for card in player.set_aside:
        player.hand.append(card)
    player.set_aside.clear()

    if player.permanents.get("coin"):
        player.resources.coin += player.permanents["coin"]


def _apply_training_rewards(player: Player, log: EventLog) -> None:
    """La pista de Entrenamiento sube el límite de quemas hasta 4 al final."""
    limit = 1 + player.training // 3
    if limit > player.tokens.burn_limit:
        player.tokens.burn_limit = min(4, limit)
        log.emit("burn-limit", player.id, limit=player.tokens.burn_limit)


def end_turn(state: GameState, player: Player, log: EventLog) -> None:
    """Pasos 5-6: descartar lo jugado y la mano, y robar 5 nuevas."""
    player.cleanup(state.rng)
    draw = HAND_SIZE + player.permanents.get("draw", 0)
    if any(a.card.ongoing == "draw_extra_card_on_hand_draw" for a in player.allies):
        draw += 1
    player.draw(draw, state.rng)
    for track in state.tracks:
        track.sensed.clear()
    log.emit("turn-end", player.id, hand=len(player.hand), health=player.health)
