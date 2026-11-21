"""Hook de Claude Code `.claude/hooks/guardia_git.py`: push, atribución y tests."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "guardia_git.py"
_spec = importlib.util.spec_from_file_location("guardia_git", RUTA)
guardia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guardia)


@pytest.fixture
def repo(tmp_path):
    """Repo vacío; la rama se fija con checkout -b (no hace falta ningún commit)."""
    subprocess.run(["git", "init", "-q", "-b", "feature/x", str(tmp_path)], check=True)

    def en(rama):
        subprocess.run(["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", f"refs/heads/{rama}"],
                       check=True)
        return str(tmp_path)
    return en


@pytest.fixture(autouse=True)
def sin_tests_reales(monkeypatch):
    """El hook pasaría la suite entera en cada commit: aquí nunca. Y sin el
    CLAUDE_PROJECT_DIR que hereda la suite cuando la lanza el propio hook."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    llamadas = []
    monkeypatch.setattr(guardia, "fallo_de_tests", lambda cwd: llamadas.append(cwd))
    return llamadas


@pytest.mark.parametrize("cmd", [
    "git push origin develop",
    "git push origin HEAD:main",
    "git push --force origin +feature/x:develop",
    "git push origin feature/x:refs/heads/main",
    "git push --all origin",
    "git push origin --delete main",
    "git -C . push origin develop",
    "cd /tmp && git push origin main",
    "GIT_TRACE=1 git push origin develop",
    'git push origin develop "',
])
def test_push_a_rama_protegida_se_bloquea(cmd, repo):
    assert guardia.motivo_bloqueo(cmd, repo("feature/x"))


@pytest.mark.parametrize("cmd", [
    "git push -u origin feature/claude-code-setup",
    "git push origin HEAD",
    "git push",
    "git push --force-with-lease origin feature/x",
    "git -C . push -o ci.skip origin feature/x",
])
def test_push_a_rama_de_trabajo_pasa(cmd, repo):
    assert guardia.motivo_bloqueo(cmd, repo("feature/x")) is None


@pytest.mark.parametrize("rama", ["develop", "main"])
def test_push_sin_destino_estando_en_rama_protegida(rama, repo):
    cwd = repo(rama)
    assert guardia.motivo_bloqueo("git push", cwd)
    assert guardia.motivo_bloqueo("git push origin HEAD", cwd)
    assert guardia.motivo_bloqueo(f"cd {cwd} && git push", "/")


@pytest.mark.parametrize("cmd", [
    "git push 2>&1 | tail -3",
    "git push origin > /dev/null",
    "git push origin develop 2>&1",
    "git push origin &> log.txt",
    "git add -A &&\ngit commit -m x &&\ngit push origin develop",
    "git status;\ngit push",
    'cat <<< "hola"\ngit push origin develop',
])
def test_redirecciones_y_operadores_al_final_de_linea(cmd, repo):
    assert guardia.motivo_bloqueo(cmd, repo("develop"))


def test_otro_repo_no_es_asunto_del_hook(repo, tmp_path_factory, monkeypatch):
    cwd = repo("develop")
    otro = tmp_path_factory.mktemp("otro")
    subprocess.run(["git", "init", "-q", str(otro)], check=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(otro))
    assert guardia.motivo_bloqueo("git push origin develop", cwd) is None
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", cwd)
    assert guardia.motivo_bloqueo("git push origin develop", cwd)


def test_un_heredoc_que_menciona_push_no_es_un_push(repo):
    cmd = "cat <<'EOF' > nota.txt\ngit push origin develop\nEOF"
    assert guardia.motivo_bloqueo(cmd, repo("feature/x")) is None


def test_commit_con_atribucion_se_bloquea_sin_pasar_tests(repo, sin_tests_reales):
    cmd = ("git commit -q -F - <<'EOF'\nAdd thing\n\n"
           "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nEOF")
    assert "atribución" in guardia.motivo_bloqueo(cmd, repo("feature/x"))
    assert sin_tests_reales == []


def test_commit_con_fichero_de_mensaje_con_atribucion(repo, tmp_path):
    msg = tmp_path / "msg.txt"
    msg.write_text("Fix\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n")
    assert guardia.motivo_bloqueo(f"git commit -F {msg}", repo("feature/x"))


def test_commit_limpio_pasa_por_los_tests(repo, sin_tests_reales, monkeypatch):
    cwd = repo("feature/x")
    assert guardia.motivo_bloqueo('git commit -m "Add guard"', cwd) is None
    assert sin_tests_reales == [cwd]
    monkeypatch.setattr(guardia, "fallo_de_tests", lambda cwd: "los tests fallan")
    assert "los tests fallan" in guardia.motivo_bloqueo('git commit -m "Add guard"', cwd)


@pytest.mark.parametrize("cmd", [
    'gh pr create --base develop --title T --body "x\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"',
    'gh release create v1.0.0 --notes "Co-Authored-By: Claude <noreply@anthropic.com>"',
])
def test_gh_con_atribucion_se_bloquea(cmd, repo):
    assert guardia.motivo_bloqueo(cmd, repo("feature/x"))


def test_gh_sin_atribucion_y_coautor_humano_pasan(repo):
    cmd = 'gh pr create --base develop --title T --body "Co-authored-by: Ana <ana@example.com>"'
    assert guardia.motivo_bloqueo(cmd, repo("feature/x")) is None


def test_extremo_a_extremo_por_stdin(repo):
    cwd = repo("feature/x")

    def hook(cmd):
        entrada = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
        return subprocess.run([sys.executable, str(RUTA)], input=entrada,
                              capture_output=True, text=True, check=True).stdout

    salida = json.loads(hook("git push origin develop"))["hookSpecificOutput"]
    assert salida["permissionDecision"] == "deny"
    assert hook("ls -la") == ""
    assert hook("git push -u origin feature/x") == ""
    # Commit real del hook (sin monkeypatch): sin venv no hay tests, así que se deniega.
    motivo = json.loads(hook('git commit -m "x"'))["hookSpecificOutput"]["permissionDecisionReason"]
    assert ".venv-clearvoice" in motivo
