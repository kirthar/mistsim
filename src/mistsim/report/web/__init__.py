"""Generación de HTML estático autocontenido: reproductor de partida y explorador de cartas.

Sin servidor, sin dependencias externas (ni CDN, ni npm, ni frameworks): cada página es
un único fichero `.html` con su CSS y su JS embebidos. `build.build_report` es el punto
de entrada que usa `mistsim report`.
"""
from __future__ import annotations

from mistsim.report.web.build import build_report

__all__ = ["build_report"]
