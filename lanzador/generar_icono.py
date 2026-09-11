#!/usr/bin/env python3
"""Genera el icono de la app a partir de docs/img/icon.png.

El PNG de origen tiene el cuadrado redondeado sobre fondo blanco y sin
alfa. Aquí: el fondo conectado con el borde pasa a transparente (la oveja
blanca de dentro se conserva), se recorta al cuadrado y se centra en un
lienzo 1024×1024 con el margen que usan los iconos de macOS (~10 %).

Salidas:
  <destino>/icon.iconset/…   (tamaños 16-512 @1x/@2x, para iconutil)
  <destino>/icon_1024.png
  app/recursos/icon_512.png  (icono de la ventana Qt)

Uso: generar_icono.py docs/img/icon.png <carpeta_destino>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

TAMANO_LIENZO = 1024
MARGEN = 0.10  # fracción del lienzo a cada lado
UMBRAL_BLANCO = 235


def fondo_transparente(img: Image.Image) -> Image.Image:
    rgba = np.array(img.convert("RGBA"))
    casi_blanco = (rgba[:, :, :3] >= UMBRAL_BLANCO).all(axis=2)
    etiquetas, _ = ndimage.label(casi_blanco)
    borde = np.concatenate([etiquetas[0, :], etiquetas[-1, :],
                            etiquetas[:, 0], etiquetas[:, -1]])
    exteriores = set(np.unique(borde)) - {0}
    fondo = np.isin(etiquetas, list(exteriores))
    rgba[fondo, 3] = 0
    return Image.fromarray(rgba)


def recortar_y_centrar(img: Image.Image) -> Image.Image:
    alfa = np.array(img)[:, :, 3]
    filas = np.where(alfa.any(axis=1))[0]
    columnas = np.where(alfa.any(axis=0))[0]
    recorte = img.crop((columnas[0], filas[0], columnas[-1] + 1, filas[-1] + 1))
    lado = int(TAMANO_LIENZO * (1 - 2 * MARGEN))
    recorte = recorte.resize((lado, lado), Image.LANCZOS)
    lienzo = Image.new("RGBA", (TAMANO_LIENZO, TAMANO_LIENZO), (0, 0, 0, 0))
    desplazamiento = (TAMANO_LIENZO - lado) // 2
    lienzo.paste(recorte, (desplazamiento, desplazamiento), recorte)
    return lienzo


def main(origen: Path, destino: Path) -> None:
    icono = recortar_y_centrar(fondo_transparente(Image.open(origen)))
    destino.mkdir(parents=True, exist_ok=True)
    icono.save(destino / "icon_1024.png")
    iconset = destino / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for tamano in (16, 32, 128, 256, 512):
        icono.resize((tamano, tamano), Image.LANCZOS).save(
            iconset / f"icon_{tamano}x{tamano}.png")
        icono.resize((tamano * 2, tamano * 2), Image.LANCZOS).save(
            iconset / f"icon_{tamano}x{tamano}@2x.png")
    recursos = Path(__file__).resolve().parent.parent / "app" / "recursos"
    recursos.mkdir(exist_ok=True)
    icono.resize((512, 512), Image.LANCZOS).save(recursos / "icon_512.png")
    print(f"icono generado en {destino} y {recursos / 'icon_512.png'}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
