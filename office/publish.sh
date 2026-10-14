#!/bin/zsh
# Refresh the PUBLIC portfolio repo (github.com/PRIBINKBENNY/agent-hq) from the private dev repo.
# Exports the current tree minus personal data, scans for secrets, and pushes a single new commit
# on top of the public history. Safe to run any time; the weekly-publish job runs it on Fridays.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_GH="${GITHUB_USER:-$(gh api user -q .login)}"
PUB="${TMPDIR:-/tmp}/agent-hq-public-$$"
rm -rf "$PUB"; mkdir -p "$PUB"
cd "$ROOT"
git archive HEAD | tar -x -C "$PUB"
rm -rf "$PUB/workspace" "$PUB/office/eval/results" "$PUB/office/logs"
mkdir -p "$PUB/workspace"
printf '# workspace\n\nAgent output lives here: `cv/`, `applications/`, `posts/`, `projects/`, `roadmap.md`, `plan-90-days.md`, `offer.md`.\nPersonal files are kept out of the public repo.\n' > "$PUB/workspace/README.md"
cd "$PUB"
if grep -rIlE --exclude=publish.sh "gsk_[A-Za-z0-9]{20}|csk-[A-Za-z0-9]{20}|\+44 ?7|pribinbenny471|07587" . >/dev/null 2>&1; then
  echo "ABORT: secret or personal contact detail found in export"; grep -rIlE --exclude=publish.sh "gsk_[A-Za-z0-9]{20}|csk-[A-Za-z0-9]{20}|\+44 ?7|pribinbenny471|07587" .; exit 1
fi
git init -q -b main
git remote add origin "https://github.com/$USER_GH/agent-hq.git"
git fetch -q origin main
git reset -q --soft origin/main          # keep public history, replace the tree
git add -A
if git diff --cached --quiet; then echo "public repo already up to date"; exit 0; fi
MSG="${1:-Sync from dev: $(git -C "$ROOT" log -1 --pretty=%s)}"
git -c user.name="Pribin K Benny" -c user.email="46479115+PRIBINKBENNY@users.noreply.github.com" -c commit.gpgsign=false commit -q -m "$MSG"
git push -q origin main
echo "published: https://github.com/$USER_GH/agent-hq ($(git rev-parse --short HEAD))"
rm -rf "$PUB"
