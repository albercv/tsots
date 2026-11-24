---
name: release
description: Use when the user asks to cut, publish or prepare a TSOTS release (vX.Y.Z) from develop to main, including the release PR, the tag, the GitHub release notes and the cleanup of merged branches and worktrees.
argument-hint: "[vX.Y.Z]"
disable-model-invocation: true
---

# Release $ARGUMENTS

Source of truth: `docs/DEVELOPMENT.md` → "Branches and releases". Never push to
`develop` or `main`; the only thing this skill pushes is the tag.
No AI attribution in any PR, tag, release or commit.

Never `checkout`/`pull` in `~/Documents/personalProjects/limpiadorVideo`: that
checkout is the user's installed app and they upgrade it themselves.

## 1. Check that develop is ready

1. `git fetch origin --tags`
2. Last release: `PREV=$(git describe --tags --abbrev=0 origin/main)`.
   Pending: `git log --oneline --first-parent $PREV..origin/develop`. Empty → stop, nothing to release.
3. Open PRs against develop: `gh pr list --base develop`. List them; the user
   decides whether they wait for the next release.
4. Run the suite on exactly `origin/develop` (a clean worktree or the current
   one if it is at that commit):
   `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q`
   Any failure → stop and report it. (In a worktree the venv lives in the main
   checkout: `../limpiadorVideo/.venv-clearvoice/bin/python`.)

## 2. Version

If `$ARGUMENTS` is empty, propose one from `$PREV`: patch for fixes only,
minor if any merged PR adds a feature. Ask the user to confirm the version.

## 3. Release PR (develop → main)

Collect the merged PRs: `gh pr list --state merged --base develop --search "merged:>=<date of $PREV>" --json number,title,body`.

Body in Spanish, same sections as every PR here:

- `## Qué cambia` — one bullet per PR, `**Título** (#N)` + one line.
- `## Por qué` — the user-facing reason for the release.
- `## Cómo se ha verificado` — the suite result from step 1 (count, failures).
- `## Qué tienes que saber` — upgrade steps (does `requirements.txt` change
  between `$PREV` and develop? then `instalar.command` is needed), risks.

`gh pr create --base main --head develop --title "Release vX.Y.Z" --body-file <file>`

Give the user the PR link and **stop**. They merge it on GitHub with
"Create a merge commit". Continue only when they say it is merged.

## 4. Tag and GitHub release

1. `git fetch origin` and confirm the PR is merged: `gh pr view <N> --json state -q .state` → `MERGED`.
2. Tag the merge commit on main without checking it out:
   `git tag -a vX.Y.Z origin/main -m "vX.Y.Z: <one-line summary>"` then `git push origin vX.Y.Z`.
3. Release notes in **English**, user-facing, same shape as previous releases
   (`gh release view $PREV`):

   ```
   ## New since vPREV

   **<Feature in plain words>** (#N)
   - what the user sees / can do now
   - limits or side effects worth knowing

   **Upgrading:**
   - Download `main` again, or run `git pull`.
   - Run `instalar.command` again (only if requirements.txt changed).
   - Reopen the app.
   ```

   `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <file>`

## 5. Cleanup (ask first)

List what is now merged into `origin/main`:
`git worktree list`, `git branch --merged origin/main`.
Propose removing those worktrees (`git worktree remove <path>`) and local
branches (`git branch -d <name>`). Remove only what the user confirms; never
`-D`, never a worktree with uncommitted changes.

## 6. Report

Release URL, tag, and the upgrade line for the user's install:
`cd ~/Documents/personalProjects/limpiadorVideo && git pull` (+ `instalar.command` if needed) and reopen the app.
