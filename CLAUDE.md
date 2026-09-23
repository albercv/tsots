# Rules for AI agents working on this repository

- **Never push to `develop` or `main`.** Every change goes through a pull
  request: branch off `develop`, push the branch, open a PR against
  `develop`. Releases are a PR from `develop` to `main`. Details in
  `docs/DEVELOPMENT.md` → "Branches and releases".
- **No documentation-only PRs.** Docs, TODO updates and plans travel in
  the branch of the feature they belong to and reach `develop` when that
  branch is merged.
- Commits and PR descriptions carry no AI attribution (no `Co-Authored-By`
  trailer, no "Generated with" line). Commit messages in English.
- Run the tests before committing and commit only if they pass:
  `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q`
- Code, comments and GUI text are in Spanish; translate new GUI strings with
  `lanzador/traducir.sh` and `locale/en/LC_MESSAGES/tsots.po`.
- Pending work lives in `docs/TODO.md`.
