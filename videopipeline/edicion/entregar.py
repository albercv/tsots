"""Guardián de la entrega: solo el script del agente entrega, nunca Haiku."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from videopipeline.edicion.componer import _duracion, _tiene_audio

TOLERANCIA_DURACION = 0.25
TOLERANCIA_MTIME = 0.001


def origen_cambiado(datos: dict) -> str | None:
    """Motivo si el original ya no es el que se cortó (ausente o modificado)."""
    origen = Path(datos["origen"])
    if not origen.exists():
        return "origen cambiado: el original ya no existe"
    st = origen.stat()
    if st.st_size != datos["origen_tam"] or abs(st.st_mtime - datos["origen_mtime"]) > TOLERANCIA_MTIME:
        return "origen cambiado: el original se modificó durante la edición"
    return None


def _comprobar(trabajo: Path, datos: dict) -> str | None:
    salida = trabajo / "salida.mp4"
    if not salida.exists():
        return "No existe salida.mp4"
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(salida)],
        capture_output=True, text=True).stdout.strip()
    if dims != "1080,1920":
        return f"salida.mp4 no es 1080x1920 (ffprobe: {dims or 'sin vídeo'})"
    if not _tiene_audio(salida):
        return "salida.mp4 no tiene pista de audio"
    d_sal, d_vid = float(_duracion(salida)), float(_duracion(trabajo / "video.mp4"))
    if abs(d_sal - d_vid) > TOLERANCIA_DURACION:
        return f"La duración no cuadra: salida {d_sal:.2f} s, vídeo {d_vid:.2f} s"
    return origen_cambiado(datos)


def entregar(trabajo: Path) -> str | None:
    trabajo = Path(trabajo)
    try:
        datos = json.loads((trabajo / "trabajo.json").read_text("utf-8"))
        motivo = _comprobar(trabajo, datos)
    except Exception as e:  # noqa: BLE001
        return f"No se pudo comprobar la salida: {e}"
    if motivo:
        return motivo
    destino = Path(datos["destino"])
    if destino.resolve() == Path(datos["origen"]).resolve():
        return "El destino coincide con el original; no se sobrescribe"
    if not destino.name.endswith(".editado.mp4"):
        return f"El destino debe acabar en .editado.mp4: {destino.name}"
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        duracion = float(_duracion(trabajo / "salida.mp4"))
        with open(trabajo / "salida.mp4", "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, destino)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return f"No se pudo copiar el resultado: {e}"
    # Entregado: un fallo de limpieza ya no cambia el resultado, solo avisa.
    try:
        (trabajo / "video.mp4").unlink(missing_ok=True)
        (trabajo / "salida.mp4").unlink(missing_ok=True)
        (trabajo / "resultado.json").write_text(json.dumps(
            {"destino": str(destino), "estilo": datos["estilo"], "duracion": duracion,
             "fecha": datetime.now().astimezone().isoformat(timespec="seconds")},
            ensure_ascii=False), "utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"Aviso: entregado, pero falló la limpieza del trabajo: {e}", file=sys.stderr)
    return None


def main(args: list[str]) -> int:
    try:
        if args[0] == "--solo-origen":  # antes de gastar claude en un trabajo ya caducado
            motivo = origen_cambiado(json.loads((Path(args[1]) / "trabajo.json").read_text("utf-8")))
            if motivo:
                print(motivo)
            return 1 if motivo else 0
        motivo = entregar(Path(args[0]))
        if motivo:
            print(motivo)
            return 1
        print(json.loads((Path(args[0]) / "trabajo.json").read_text("utf-8"))["destino"])
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Error inesperado al entregar: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
