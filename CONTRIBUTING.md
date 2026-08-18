# Trabajar en paralelo sobre mistsim

La 2ª entrega son cuatro líneas de trabajo independientes que corren a la vez. Este
documento es el contrato que las mantiene sin pisarse.

## El sustrato ya está (Fase A)

Estas cuatro piezas están congeladas: se les pueden **añadir** campos, pero no
renombrarlos ni cambiar sus firmas, porque los cuatro streams dependen de ellas.

| Pieza | Dónde | Para qué |
|---|---|---|
| `PlayerResult` | `engine/game.py` | Qué hizo cada jugador, derivado del log **una sola vez** |
| `serial` | `io/serial.py` | Partidas, logs y perfiles a JSON; corpus JSONL en streaming |
| `run_batch` | `sim/batch.py` | Lotes en paralelo, reproducibles |
| `GameState.clone()` | `domain/state.py` | Explorar una rama sin destruir el estado |

### Lo que conviene saber de cada una

**`PlayerResult`** — no vuelvas a escanear el log para sacar compras, daño o puntos de
misión. Ya está en `result.players[seat]`. Si necesitas una métrica que no está, añade el
campo aquí y no un escaneo paralelo en tu módulo: el objetivo es que los cuatro streams
midan lo mismo.

**`run_batch`** — las semillas se derivan del **índice** de partida, no de un RNG
compartido, y el pool devuelve en orden. Por eso un lote da la misma secuencia con 1
worker y con 8, y hay un test que lo comprueba. Si algún día eso se rompe, ningún
resultado del optimizador es comparable con el anterior.

`collect_log=False` no acelera apenas (el cuello de botella es el scoring del agente,
no el log), pero reduce el corpus un 90%: 562 → 58 eventos por partida. Úsalo para
corpus grandes; deja el log completo si vas a reproducir la partida.

**`GameState.clone()`** — cuesta **0,14 ms**. Está escrito a mano en vez de con
`deepcopy` porque así es 29 veces más rápido: comparte las definiciones inmutables
(`Card`, `Ability`, `Mission`, `Character`) y sólo copia lo que muta. Con eso un beam de
30 a profundidad 12 sale por 0,05 s.

> Si añades un campo **mutable** a `GameState`, `Player`, `Market` o `MissionTrack`,
> refléjalo en `clone()`. `test_clone_matches_deepcopy_field_by_field` compara contra la
> copia profunda genérica y fallará si se te olvida.

## Añadir un subcomando

Crea `src/mistsim/cli/commands/<nombre>.py` con:

```python
def register(subparsers) -> None:
    parser = subparsers.add_parser("<nombre>", help="...")
    parser.set_defaults(func=cmd_<nombre>)
```

Se descubre solo. **No edites `cli/main.py`** — no conoce ningún comando concreto, y ése
es justo el punto: cuatro streams añaden el suyo sin tocar un fichero común.

Lo compartido entre comandos vive en `cli/common.py` (`add_game_args`, `config_from`,
`resolve_strategies`, `warn_homebrew`).

## Reglas de convivencia

1. Ramifica de `claude/mistborn-card-simulator-l3x0pg`. Una rama por stream.
2. **No toques ficheros fuera de tu lista.** Si necesitas un cambio en código compartido,
   no lo hagas por tu cuenta: es un punto de coordinación.
3. Tus tests van en `tests/test_<stream>.py`. **No edites tests existentes** — si uno
   falla por tu culpa, el fallo es tuyo, no del test.
4. `pytest` y `ruff check src tests scripts` en verde antes de cada commit.

### Propiedad de ficheros

| Stream | Ficheros propios |
|---|---|
| Optimizador | `optimize/**`, `cli/commands/optimize.py`, `tests/test_optimize.py` |
| Combos | `analysis/**`, `cli/commands/combos.py`, `tests/test_analysis.py` |
| Solver | `engine/solver.py`, `agents/solver_agent.py`, `cli/commands/solve.py`, `tests/test_solver.py` |
| Visor web | `report/web/**`, `cli/commands/report.py`, `tests/test_web.py` |

Intersección vacía. Los cuatro **leen** el motor y `io/`; ninguno los escribe.

## Antes de dar por bueno un resultado

Las **Misiones** y el **mazo del Lord Ruler** siguen siendo homebrew: los valores están
inventados y `mistsim validate` lo dice. Hoy el 84% de las partidas a 3 jugadores termina
por completar Misiones, y ese número sale de esa reconstrucción, no del juego. Cualquier
informe que dependa de ello debe decirlo.

## Lección de la Fase A

Los tests de clonado destaparon tres fallos encadenados que llevaban desde el commit del
motor falseando **todas** las partidas: el Mercado servía las 82 cartas en vez de 6, Seek
se recursaba sin fin, y las 6 Financiaciones del mazo inicial no se podían activar nunca
—o sea, nadie tenía monedas de salida—. Los números del meta cambiaron por completo al
corregirlo.

Moraleja para los cuatro streams: **si un resultado agregado sale raro, sospecha del
motor antes que de la estrategia.** Y escribe el test que compara contra una
implementación de referencia, aunque parezca redundante: los tres fallos salieron de un
test que sólo pretendía comprobar que `clone()` copiaba bien.
