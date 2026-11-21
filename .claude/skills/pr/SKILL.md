---
name: pr
description: Use when the work on a feature/fix branch of TSOTS is done and the user asks to push it and open the pull request against develop.
disable-model-invocation: true
---

# Open the PR for the current branch

Rules from `CLAUDE.md`: PRs go to `develop`, never to `main`; no docs-only PRs;
commit messages in English; no AI attribution anywhere; tests pass before
every commit.

## 1. Check the branch

- `git branch --show-current` must be `feature/*`, `fix/*` or `docs/*`. On
  `develop` or `main` → stop and tell the user.
- `git fetch origin` and `git log --oneline origin/develop..HEAD`: these are the
  commits the PR will carry. Anything unrelated → stop and ask.
- Uncommitted changes (`git status --short`) → ask whether they belong in the PR.

## 2. Make the branch complete

The branch carries everything its change needs:

- `docs/TODO.md`: remove the items this branch completes; add follow-ups it leaves.
- `docs/DEVELOPMENT.md` / `README.md` / `README.es.md`: updated if behaviour or setup changed.
- New or changed GUI strings: `lanzador/traducir.sh`, then translate the new
  `msgstr`s in `locale/en/LC_MESSAGES/tsots.po` and run it again.

## 3. Tests

`QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q`
(in a worktree: `../limpiadorVideo/.venv-clearvoice/bin/python`). Note the
counts for the PR body. A failure that is not from this branch: rerun once;
if it persists, report it in the body instead of hiding it.

## 4. Push and open the PR

`git push -u origin <branch>`

Title: what the user gets, in Spanish, not the branch name. Body in Spanish,
written to a file and passed with `--body-file`:

```
## Qué cambia
<bullets: the visible change first, then the code that makes it>

## Por qué
<the user's need, in their words when there are any>

## Cómo se ha verificado
- `pytest -q`: <N> pasan, <fallos y por qué>.
- Tests nuevos: <what each one pins>.
- Prueba real: <app / data used and the result>, or "sin prueba real" and why.

## Qué tienes que decidir o saber
<risks, assumptions, follow-ups; "nada" only if truly nothing>
```

`gh pr create --base develop --title "<title>" --body-file <file>`

Report the PR URL.
