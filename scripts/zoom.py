"""Recorta y amplía la zona de habilidades de las cartas para verificarlas a ojo.

Uso:  python scripts/zoom.py [nombre ...]      (sin args: todas)
Salida en /tmp/zoom/<nombre>.png
"""
import os
import sys

from PIL import Image

SRC, OUT = "data/images", "/tmp/zoom"


def zoom(name: str, scale: int = 4) -> None:
    im = Image.open(f"{SRC}/{name}.png")
    w, h = im.size
    # Action: la caja de habilidades ocupa la franja inferior.
    # Ally: apaisado, con coste/defensa arriba y las habilidades a la derecha.
    box = (0, int(h * 0.56), w, h) if h > w else (int(w * 0.30), 0, w, h)
    crop = im.crop(box)
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    crop.save(f"{OUT}/{name}.png")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    names = sys.argv[1:] or [f[:-4] for f in sorted(os.listdir(SRC)) if f.endswith(".png")]
    for n in names:
        zoom(n)
    print(f"{len(names)} recortes en {OUT}")
