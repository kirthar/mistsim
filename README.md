# mistsim

Simulador de **Mistborn: The Deckbuilding Game** (Brotherwise Games) en PvP y
Cooperativo, pensado además como banco de pruebas para encontrar las mejores
combinaciones de cartas.

```bash
pip install -e ".[dev]"

mistsim validate                      # comprueba los datos y su procedencia
mistsim play -p 2 --strategy aggro-combate rush-mision
mistsim batch -n 200 -p 3             # 200 partidas, resumen de resultados
mistsim tourney -n 20                 # liguilla de todos los arquetipos
mistsim cards Dominate                # ficha de una carta y sus sinergias
mistsim cards --metal Zinc --tag ally

mistsim batch -n 5000 -w 8 --save corpus.jsonl   # lote paralelo, guardado como corpus
```

## Estado de los datos

Esto importa antes que el código: **parte del contenido del juego no está publicado
en ninguna fuente** y ha habido que reconstruirlo. `mistsim validate` lo dice siempre,
y el CLI avisa por stderr cuando una partida descansa en datos inventados.

| Contenido | Estado |
|---|---|
| 65 cartas de Mercado | **Verificado** carta a carta contra sus imágenes |
| 5 personajes y sus habilidades de Nivel I | **Verificado** (datos del propietario del juego) |
| Mazo inicial (4 Entrenamiento + 6 Financiación) | **Verificado** (datos del propietario) |
| 8 cartas de Misión | **Homebrew** — sólo se conocen los nombres |
| 36 cartas del Lord Ruler | **Homebrew** — ninguna transcrita |

Sustituir el contenido homebrew por datos reales es editar `data/missions.json` y
`data/lord_ruler.json`. El motor los consume igual: no hay que tocar código.

### Correcciones a la transcripción de partida

La transcripción previa de las 65 cartas tenía **30 errores en 25 cartas**, todos
detectados al ampliar las imágenes ×4. Están documentados uno a uno en
[`data/verify/DIFF.md`](data/verify/DIFF.md). Los tres patrones:

- El número de combate va **dentro** del glifo de espadas; se había tomado el número
  del keyword contiguo (`PUSH 1`, `PULL 1`). Assassinate, Crash, Lurcher, Precise Shot
  y Rescue figuraban todas con combate 1.
- El **cuadrado** de misión y el **círculo** de moneda son casi idénticos a 300 px.
- `+2 METAL` leído como `+METAL` en siete cartas, lo que falseaba su coste real.

El set queda validado de forma independiente: los 65 números impresos `N/82` son
distintos y dejan 17 huecos, que son exactamente las 17 cartas con 2 copias.

## Arquitectura

Tres capas desacopladas. El JSON se lee en un solo sitio y el motor no toca disco.

```
src/mistsim/
  content/   carga y validación de los datos
  domain/    estado puro: cartas, metales, jugador, mercado, misiones
  engine/    reglas: efectos, turno, combate, Lord Ruler
  agents/    estrategia: etiquetas, sinergias, perfiles, arquetipos
  io/        serialización y corpus JSONL
  sim/       lotes de partidas en paralelo
  cli/       punto de entrada + un fichero por subcomando
  report/    log legible turno a turno
```

Para trabajar en paralelo sobre el repo, ver [CONTRIBUTING.md](CONTRIBUTING.md): describe
los contratos congelados (`PlayerResult`, `serial`, `run_batch`, `GameState.clone`), cómo
añadir un subcomando sin tocar `main.py`, y el reparto de ficheros entre líneas de trabajo.

### El turno es un espacio de acciones, no un guion

El turno real es *"en cualquier orden y cualquier número de veces"*, así que el motor
expone `legal_actions(state)` y `apply(state, action)` en vez de una secuencia fija.

Es la decisión que sostiene el resto: el solver de turno óptimo y un MCTS necesitan
ramificar sobre ese espacio. Con un turno guionizado habría que reescribir el motor
entero para añadirlos.

### Los efectos son un registro, no un `if` gigante

Las cartas usan 55 claves de efecto distintas. Cada una es una función registrada con
`@effect("coin")`. Añadir una carta es tocar `data/`, no el motor. Una clave
desconocida lanza `UnknownEffect` en vez de resolverse a nada en silencio, que es como
una simulación acaba dando resultados plausibles y falsos. Hay un test que comprueba la
correspondencia en ambos sentidos: ningún efecto sin resolutor, ningún resolutor sin uso.

### Las estrategias son pesos, no guiones

Un arquetipo es un `StrategyProfile`: pesos por recurso, afinidad por metal, afinidad
por etiqueta y peso de la sinergia. El valor de compra de una carta es

```
valor_base(carta) + Σ sinergia(carta, cartas_que_ya_tienes)
```

Ese `Σ` es lo que hace que las estrategias **combinen cartas por sinergia real** y no
por metal. Las reglas están en `agents/synergy.py`, cada una justificada por una
interacción mecánica concreta: `Rebel` escala con cada Aliado en mesa, `Dominate` sólo
brilla con muchas fuentes de misión que convertir, `Confrontation` no vale nada sin
generación de Atium, `Ascendant` quiere cartas caras que rescatar del descarte.

## Los 11 arquetipos

| Arquetipo | Motor |
|---|---|
| `rush-mision` | Corre las tres pistas; Estaño/Latón/Bronce y efectos según posición |
| `aggro-combate` | Mata jugadores; Peltre/Acero, ignora las Misiones |
| `muro-defender` | Defenders y curación; gana por desgaste |
| `motor-riot` | Zinc; llena la mesa de Aliados y los activa sin quemar |
| `tempo-seek` | Bronce; usa el Mercado con Seek sin comprarlo |
| `adelgazar` | Latón; elimina tus cartas de salida hasta que todo robo sea bueno |
| `recursion-hierro` | Hierro/Acero; Pull para apilar, Push para negar |
| `combo-atium` | Vía alternativa: 4 Atium en Confrontation y victoria instantánea |
| `rampa-economica` | Monedas primero, cartas gordas después |
| `motor-robo` | Cadenas de robo; más cartas, más metales activos |
| `equilibrado` | Sin sesgos; la referencia contra la que medir a los demás |

Ninguno se define por "los metales de mi personaje": cada uno se define por un motor de
cartas, y el personaje es un modificador.

## Estado del meta

Liguilla de 12 partidas por emparejamiento (`mistsim tourney -n 12 -s 100`):

```
muro-defender      55.8%      equilibrado        51.7%
aggro-combate      55.0%      motor-riot         49.2%
recursion-hierro   55.0%      rampa-economica    49.2%
adelgazar          51.7%      motor-robo         47.5%
combo-atium        51.7%      tempo-seek         42.5%
                              rush-mision        40.8%
```

Reparto de 15 puntos, sin estrategias dominantes ni muertas.

**Aviso:** en batch a 3 jugadores el 84% de las partidas termina por completar las tres
Misiones. Es consecuencia directa de que los valores de las Misiones son homebrew, así
que ese número dice más de esa reconstrucción que del juego real. No se ha ajustado a
ojo precisamente por eso: la calibración honesta llega cuando se fotografíen las 8
cartas.

## Tests

```bash
pytest          # 55 tests
ruff check src tests scripts
```

Los invariantes se comprueban al final de **cada turno** de partidas completas a 2, 3 y
4 jugadores y en coop: ninguna carta se duplica ni se pierde entre zonas, la salud se
mantiene en 0-40 y las monedas nunca son negativas.

## Decisiones de reglas

`data/RULES_DECISIONS.md` recoge cada conflicto y cómo se resolvió. El orden de
precedencia es: **FAQ oficial > imagen de la carta > manual > guías comunitarias**.
El conflicto de fondo era `metals.json`, que decía que un metal flareado podía
refrescarse y volver a usarse el mismo turno; el FAQ dice lo contrario y manda el FAQ.
Cada decisión discutible es un flag en `GameConfig`, para poder medir la lectura
alternativa.

## Siguiente entrega

El motor está construido para soportarlos, pero aún no existen:

- **Optimizador de mazos** — algoritmo genético sobre el espacio de pesos de
  `StrategyProfile`, para derivar la lista de compra óptima por personaje y modo.
- **Minería de combos** — lift/soporte sobre miles de partidas, para medir qué pares y
  tríos de cartas rinden por encima de la suma de sus partes.
- **Solver de turno óptimo** — branch-and-bound sobre `legal_actions` para máximo daño
  o máximos puntos de misión dada una mano, y de paso una IA mucho más fuerte.
- **Visor web de partida** y **explorador de cartas/combos**.
