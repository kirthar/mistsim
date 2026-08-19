"""Motor de reglas.

Importar el paquete registra los efectos especiales. Sin esto, `resolve` sólo conoce
los del núcleo y una carta con efecto especial lanza `UnknownEffect` según quién haya
importado qué antes — un footgun de orden de importación que ya mordió al escribir los
tests de Misión.
"""
from mistsim.engine import effects_special as _effects_special  # noqa: F401
