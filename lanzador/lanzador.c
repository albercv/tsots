/* Lanzador nativo de TheSilenceOfTheShorts.app.
 *
 * Por qué un binario y no un script: si el ejecutable principal del bundle
 * es un script, el proceso "responsable" ante TCC es /bin/bash (binario de
 * Apple) y macOS deniega el acceso a Documentos sin preguntar. Con un
 * binario propio, macOS muestra el diálogo de permiso a nombre de la app y
 * el permiso cubre a python, ffmpeg y auto-editor (hijos del mismo PID).
 *
 * Compilar: clang -O2 -o TheSilenceOfTheShorts.app/Contents/MacOS/TheSilenceOfTheShorts lanzador/lanzador.c
 */
#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

static void fallo(const char *que) {
    fprintf(stderr, "lanzador: %s: %s\n", que, strerror(errno));
    exit(1);
}

/* ¿Arranca `interprete -c pass` y sale con 0? Un fallo de dyld termina por
 * señal (no "exited"), así que también se detecta. */
static int interprete_funciona(const char *interprete) {
    char *argv_t[] = {(char *)interprete, "-c", "pass", NULL};
    pid_t hijo;
    if (posix_spawn(&hijo, interprete, NULL, NULL, argv_t, environ) != 0)
        return 0;
    int estado = 0;
    if (waitpid(hijo, &estado, 0) < 0) return 0;
    return WIFEXITED(estado) && WEXITSTATUS(estado) == 0;
}

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX];
    uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0 || realpath(exe, real) == NULL)
        fallo("ruta del ejecutable");
    /* real = <proyecto>/TheSilenceOfTheShorts.app/Contents/MacOS/TheSilenceOfTheShorts */
    for (int i = 0; i < 4; i++) {
        char *s = strrchr(real, '/');
        if (s == NULL) fallo("estructura del bundle");
        *s = '\0';
    }
    const char *proyecto = real;
    if (chdir(proyecto) != 0) fallo("chdir al proyecto");

    /* Desde el Dock no hay terminal: todo lo que escriban python/Qt va al log. */
    mkdir("logs", 0755);
    FILE *log = fopen("logs/lanzador.log", "a");
    if (log != NULL) {
        time_t t = time(NULL);
        char fecha[32];
        strftime(fecha, sizeof fecha, "%F %T", localtime(&t));
        fprintf(log, "=== %s lanzando desde %s\n", fecha, proyecto);
        fflush(log);
        dup2(fileno(log), STDOUT_FILENO);
        dup2(fileno(log), STDERR_FILENO);
        fclose(log);
    }

    /* Las apps lanzadas desde el Dock no heredan el PATH de la terminal. */
    const char *path_viejo = getenv("PATH");
    char path[8192];
    snprintf(path, sizeof path,
             "/opt/homebrew/bin:/opt/homebrew/opt/ffmpeg-full/bin:/usr/local/bin:%s",
             path_viejo ? path_viejo : "/usr/bin:/bin:/usr/sbin:/sbin");
    setenv("PATH", path, 1);
    char venv[PATH_MAX];
    snprintf(venv, sizeof venv, "%s/.venv-clearvoice", proyecto);
    setenv("VIRTUAL_ENV", venv, 1);

    /* Impide que el Mac duerma mientras viva este PID (execv lo conserva). */
    char pid[16];
    snprintf(pid, sizeof pid, "%d", getpid());
    char *argv_caf[] = {"caffeinate", "-i", "-w", pid, NULL};
    pid_t caf;
    posix_spawn(&caf, "/usr/bin/caffeinate", NULL, NULL, argv_caf, environ);

    /* El python del venv es un stub que salta a Python.app del framework, y
     * entonces macOS identifica el proceso como "Python" (icono del Dock,
     * permisos). Se ejecuta en su lugar una copia del intérprete dentro de
     * ESTE bundle y se le indica el venv con __PYVENV_LAUNCHER__, igual que
     * hace el stub oficial (Mac/Tools/pythonw.c de CPython). */
    char launcher[PATH_MAX], interprete[PATH_MAX];
    snprintf(launcher, sizeof launcher, "%s/bin/python", venv);
    setenv("__PYVENV_LAUNCHER__", launcher, 1);
    snprintf(interprete, sizeof interprete,
             "%s/TheSilenceOfTheShorts.app/Contents/MacOS/python", proyecto);
    /* Sin argumentos: la app. Con argumentos (open --args ...): se pasan tal
     * cual a python, útil para diagnosticar desde el contexto del Dock. */
    char *argv_py[argc + 3];
    argv_py[0] = interprete;
    int k = 1;
    if (argc > 1) {
        for (int i = 1; i < argc; i++) argv_py[k++] = argv[i];
    } else {
        argv_py[k++] = "-m";
        argv_py[k++] = "app";
    }
    argv_py[k] = NULL;
    /* Auto-reparación: la copia del intérprete enlaza el framework de Python
     * por ruta absoluta (…/Cellar/python@3.11/<versión>/…). Tras un
     * `brew upgrade python@3.11` esa ruta desaparece y el binario muere en
     * dyld. Si no arranca, se reconstruye el bundle antes de lanzar. */
    if (!interprete_funciona(interprete)) {
        fprintf(stderr, "lanzador: el Python embebido no arranca; "
                        "reconstruyendo TheSilenceOfTheShorts.app\n");
        if (system("lanzador/construir_app.sh") != 0 || !interprete_funciona(interprete))
            fallo("no se pudo reconstruir la app (ejecuta instalar.command)");
    }
    execv(interprete, argv_py);
    fallo("exec python");  /* solo si execv falla */
    return 1;
}
