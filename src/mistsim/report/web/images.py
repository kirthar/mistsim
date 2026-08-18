"""Resuelve el fichero de imagen de cada carta y las copia junto al informe.

Las imágenes se enlazan, no se incrustan como data URI: son ~12 MB en total y meterlas
en el propio HTML infla un único fichero de texto a algo incómodo de abrir. Copiarlas a
una carpeta junto al HTML mantiene todo autocontenido (nada de red, nada de servidor)
sin ese coste — el enunciado deja elegir explícitamente entre las dos formas.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from mistsim.content.loader import DATA_DIR

IMAGES_DIR = DATA_DIR / "images"

#: El nombre de fichero no siempre es el nombre de la carta en minúsculas y sin
#: espacios: la transcripción original tiene un par de erratas de tecleo que se
#: quedaron en el nombre del fichero aunque el dato de la carta ya esté corregido.
_FILENAME_OVERRIDES = {
    "Crushing Blow": "cushingblow.png",
    "Maelstrom": "maelstorm.png",
}


def image_filename(card_name: str) -> str:
    return _FILENAME_OVERRIDES.get(card_name, card_name.lower().replace(" ", "") + ".png")


def card_image_path(card_name: str) -> Path:
    return IMAGES_DIR / image_filename(card_name)


def copy_card_images(card_names: list[str], out_dir: Path) -> dict[str, str | None]:
    """Copia las imágenes que existan a `out_dir/assets/images/`.

    Devuelve nombre de carta -> ruta relativa desde el HTML (o `None` si no hay
    imagen para esa carta, para que la página use un marcador de posición en vez de
    romper un `<img>`).
    """
    dest_dir = out_dir / "assets" / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str | None] = {}
    for name in card_names:
        src = card_image_path(name)
        if not src.exists():
            mapping[name] = None
            continue
        dest = dest_dir / src.name
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dest)
        mapping[name] = f"assets/images/{src.name}"
    return mapping
