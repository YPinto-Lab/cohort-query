#!/usr/bin/env bash
# Wire the git-guard pre-commit hook into the current repo's .git/hooks/.
# Idempotent: overwrites the hook each run.
set -euo pipefail

GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="${GUARD_DIR}/pre_commit.py"

if [[ ! -f "${HOOK_SRC}" ]]; then
  echo "git-guard: pre_commit.py not found at ${HOOK_SRC}" >&2
  exit 1
fi

GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)"
if [[ -z "${GIT_DIR}" ]]; then
  echo "git-guard: not inside a git repository" >&2
  exit 1
fi

HOOK_DST="${GIT_DIR}/hooks/pre-commit"
mkdir -p "$(dirname "${HOOK_DST}")"

cat > "${HOOK_DST}" <<EOF
#!/usr/bin/env bash
# Installed by Scripts/git-guard/install.sh — do not edit by hand.
exec python3 "${HOOK_SRC}" "\$@"
EOF
chmod +x "${HOOK_DST}"

echo "git-guard: installed pre-commit hook -> ${HOOK_DST}"
