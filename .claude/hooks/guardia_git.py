#!/usr/bin/env python3
"""Hook PreToolUse (Bash) de Claude Code: hace cumplir las reglas de CLAUDE.md.

- Nadie hace push a `develop` ni a `main` (tampoco --all/--mirror ni borrarlas).
- Ni commits ni PR/releases con atribución a la IA.
- Antes de cada `git commit` pasa la suite; si falla, el commit no se hace.

Lee el JSON del hook por stdin. Para bloquear responde con
`permissionDecision: deny`; para dejar pasar no escribe nada.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROTEGIDAS = {"develop", "main"}
OPERADORES = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&"}
ATRIBUCION = re.compile(
    r"co-authored-by:[^\n]*(claude|anthropic)|generated with \[?claude",
    re.IGNORECASE,
)
# Opciones globales de git que llevan valor aparte (git -C dir push ...).
GIT_GLOBALES_CON_VALOR = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_CON_VALOR = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_TODO = {"--all", "--mirror", "--branches"}
GH_PUBLICA = {("pr", "create"), ("pr", "edit"), ("pr", "comment"),
              ("release", "create"), ("release", "edit")}
TIEMPO_TESTS = 540  # s; el hook tiene 600 en settings.json


def sin_heredocs(cmd):
    """Quita el cuerpo de los heredocs: un mensaje que diga «git push» no es un push."""
    lineas, salida, fin = cmd.split("\n"), [], None
    for linea in lineas:
        if fin is not None:
            if linea.strip() == fin:
                fin = None
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", linea)
        if m:
            fin = m.group(1)
        salida.append(linea)
    return "\n".join(salida)


def segmentos(cmd):
    """Divide una línea de shell en órdenes simples (listas de tokens)."""
    cmd = sin_heredocs(cmd).replace("\\\n", " ")
    # El salto de línea separa órdenes salvo dentro de comillas (un --body de varias líneas).
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    resultado, actual = [], []
    for tok in lex:  # puede lanzar ValueError con comillas sin cerrar
        if tok in OPERADORES or set(tok) == {"\n"}:
            if actual:
                resultado.append(actual)
            actual = []
        else:
            actual.append(tok)
    if actual:
        resultado.append(actual)
    return resultado


def quitar_asignaciones(toks):
    i = 0
    while i < len(toks) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i]):
        i += 1
    if i < len(toks) and toks[i] in ("env", "command", "exec", "time"):
        return quitar_asignaciones(toks[i + 1:])
    return toks[i:]


def git_partes(toks, cwd):
    """('push', args, cwd) para `git [-C dir] push args`; None si no es git."""
    if not toks or Path(toks[0]).name != "git":
        return None
    i = 1
    while i < len(toks) and toks[i].startswith("-"):
        if toks[i] in GIT_GLOBALES_CON_VALOR:
            if toks[i] == "-C" and i + 1 < len(toks):
                cwd = str(Path(cwd, os.path.expanduser(toks[i + 1])))
            i += 2
        else:
            i += 1
    if i >= len(toks):
        return None
    return toks[i], toks[i + 1:], cwd


def rama_actual(cwd):
    r = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def destino_protegido(args, cwd):
    """Motivo si el push escribe o borra develop/main; None si no."""
    posicionales, i = [], 0
    while i < len(args):
        a = args[i]
        if a in PUSH_TODO:
            return f"`git push {a}` también empujaría develop/main"
        if a in PUSH_CON_VALOR:
            i += 2
            continue
        if not a.startswith("-"):
            posicionales.append(a)
        i += 1
    refspecs = posicionales[1:]
    if not refspecs:
        rama = rama_actual(cwd)
        return f"estás en `{rama}` y `git push` la empujaría" if rama in PROTEGIDAS else None
    for ref in refspecs:
        origen, _, destino = ref.lstrip("+").partition(":")
        nombre = destino or origen
        if nombre == "HEAD":
            nombre = rama_actual(cwd)
        nombre = nombre.removeprefix("refs/heads/")
        if nombre in PROTEGIDAS:
            return f"el push escribe en `{nombre}`"
    return None


def ficheros_de_mensaje(args, opciones):
    """Contenido de -F/--file/--body-file para revisar la atribución."""
    textos = []
    for i, a in enumerate(args):
        valor = None
        if a in opciones and i + 1 < len(args):
            valor = args[i + 1]
        for op in opciones:
            if op.startswith("--") and a.startswith(op + "="):
                valor = a.split("=", 1)[1]
        if valor and valor != "-":
            try:
                textos.append(Path(valor).expanduser().read_text(errors="replace"))
            except OSError:
                pass
    return "\n".join(textos)


def python_del_proyecto(cwd):
    """Python del venv: en el checkout o, en un worktree, en el checkout principal."""
    def git(*a):
        return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True).stdout.strip()
    raiz = Path(git("rev-parse", "--show-toplevel") or cwd)
    comun = Path(cwd, git("rev-parse", "--git-common-dir")).resolve().parent
    for base in (raiz, comun):
        py = base / ".venv-clearvoice" / "bin" / "python"
        if py.exists():
            return raiz, py
    return raiz, None


def fallo_de_tests(cwd):
    raiz, py = python_del_proyecto(cwd)
    if py is None:
        return "no encuentro .venv-clearvoice para pasar los tests antes del commit"
    entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        r = subprocess.run([str(py), "-m", "pytest", "-q"], cwd=raiz, env=entorno,
                           capture_output=True, text=True, timeout=TIEMPO_TESTS)
    except subprocess.TimeoutExpired:
        return f"los tests no terminaron en {TIEMPO_TESTS} s"
    if r.returncode == 0:
        return None
    cola = "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])
    return f"los tests fallan; no se commitea hasta que pasen:\n{cola}"


def motivo_bloqueo(cmd, cwd):
    try:
        ordenes = segmentos(cmd)
    except ValueError:
        # shortcut: sin poder trocear, se decide por patrones sobre el texto entero
        if re.search(r"\bgit\b.*\bpush\b.*\b(develop|main)\b", cmd):
            return "no puedo analizar el comando y parece un push a develop/main"
        if ATRIBUCION.search(cmd) and re.search(r"\bgit\b.*\bcommit\b|\bgh\s+(pr|release)\b", cmd):
            return "no puedo analizar el comando y lleva atribución a la IA (CLAUDE.md)"
        return None
    tests_pendientes = None
    for toks in ordenes:
        toks = quitar_asignaciones(toks)
        if toks[:1] == ["cd"] and len(toks) > 1:
            cwd = str(Path(cwd, os.path.expanduser(toks[1])))
            continue
        partes = git_partes(toks, cwd)
        if partes:
            sub, args, dir_git = partes
            if sub == "push":
                motivo = destino_protegido(args, dir_git)
                if motivo:
                    return f"Push bloqueado: {motivo}. Abre un PR (CLAUDE.md)."
            elif sub == "commit":
                texto = cmd + ficheros_de_mensaje(args, {"-F", "--file"})
                if ATRIBUCION.search(texto):
                    return "Commit bloqueado: lleva atribución a la IA (CLAUDE.md la prohíbe)."
                tests_pendientes = dir_git
        elif toks[:1] == ["gh"] and tuple(toks[1:3]) in GH_PUBLICA:
            texto = cmd + ficheros_de_mensaje(toks[3:], {"-F", "--body-file", "--notes-file"})
            if ATRIBUCION.search(texto):
                return f"`gh {' '.join(toks[1:3])}` bloqueado: lleva atribución a la IA (CLAUDE.md)."
    if tests_pendientes:
        fallo = fallo_de_tests(tests_pendientes)
        if fallo:
            return f"Commit bloqueado: {fallo}"
    return None


def main():
    datos = json.load(sys.stdin)
    if datos.get("tool_name") != "Bash":
        return
    cmd = datos.get("tool_input", {}).get("command", "")
    if not re.search(r"\b(git|gh)\b", cmd):
        return
    motivo = motivo_bloqueo(cmd, datos.get("cwd") or os.getcwd())
    if motivo:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": motivo,
        }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
