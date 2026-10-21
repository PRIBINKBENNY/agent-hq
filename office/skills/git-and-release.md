# Git and release hygiene (updated 2026-10-21)
- Commits: one logical change each; Conventional Commits prefixes (feat, fix, docs, test, refactor, chore); the body
  says why, not what. Never "update", "wip" or "fixes".
- Before every commit: tests pass, .gitignore excludes .env, .venv, __pycache__, data dumps, model weights and
  anything over 10 MB; grep the diff for keys (sk-, gsk_, ghp_, AIza, "password"). A leaked key means rotate it,
  not just delete the line.
- Branches: main is always releasable; feature branches for work longer than a day; squash-merge with a clean
  message. Solo projects can commit to main when tests pass.
- Versions: semantic versioning; tag releases (v1.2.0); CHANGELOG.md in Keep a Changelog format, newest first, with
  Added / Changed / Fixed / Removed.
- README is the product: what it is in one line, a screenshot or GIF, install in one command, usage in three, how to
  run tests, licence. Update it in the same commit as the feature.
- Releases to Pribin's GitHub are pre-approved for his own account only; private by default; public only when the
  README is complete and the repo contains no personal data.
- Report after every push: repo URL, commit hash and message, tests run and their result. A push with "nothing new"
  is not a release.
- Never force-push main, never rewrite published history, never commit generated artefacts you can rebuild.
Sources: Conventional Commits 1.0; Keep a Changelog 1.1; Semantic Versioning 2.0; GitHub docs on secrets scanning.
