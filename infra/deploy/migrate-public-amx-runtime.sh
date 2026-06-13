#!/usr/bin/env bash
set -euo pipefail

CANONICAL_PATH="${CANONICAL_PATH:-/home/ubuntu/amx/production/AMX}"
LEGACY_PATH="${LEGACY_PATH:-/home/ubuntu/amx/production/ConsultantAIP}"
LEGACY_ROOT_PATH="${LEGACY_ROOT_PATH:-/home/ubuntu/ConsultantAIP}"
REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/BizYan/AMX.git}"

canonical_parent="$(dirname "$CANONICAL_PATH")"
legacy_real_path=""

mkdir -p "$canonical_parent"

if [[ -L "$LEGACY_PATH" ]]; then
  legacy_target="$(readlink -f "$LEGACY_PATH")"
  if [[ "$legacy_target" != "$CANONICAL_PATH" ]]; then
    if [[ -d "$legacy_target/.git" ]]; then
      legacy_real_path="$legacy_target"
    else
      echo "Legacy compatibility link points to an unexpected target: $legacy_target" >&2
      exit 1
    fi
  fi
elif [[ -d "$LEGACY_PATH/.git" ]]; then
  legacy_real_path="$(readlink -f "$LEGACY_PATH")"
fi

if [[ -z "$legacy_real_path" && -d "$LEGACY_ROOT_PATH/.git" ]]; then
  legacy_real_path="$(readlink -f "$LEGACY_ROOT_PATH")"
fi

if [[ -d "$CANONICAL_PATH/.git" && -n "$legacy_real_path" && "$legacy_real_path" != "$CANONICAL_PATH" ]]; then
  echo "Canonical and legacy paths both exist as real directories; refusing automatic migration." >&2
  exit 1
fi

if [[ ! -d "$CANONICAL_PATH/.git" ]]; then
  if [[ -n "$legacy_real_path" ]]; then
    if [[ "$legacy_real_path" == "$LEGACY_PATH" ]]; then
      mv "$legacy_real_path" "$CANONICAL_PATH"
    else
      mv "$legacy_real_path" "$CANONICAL_PATH"
      rm "$LEGACY_PATH"
    fi
  else
    git clone "$REPOSITORY_URL" "$CANONICAL_PATH"
  fi
fi

if [[ ! -d "$CANONICAL_PATH/.git" ]]; then
  echo "Canonical AMX checkout is not a Git repository: $CANONICAL_PATH" >&2
  exit 1
fi

if [[ -e "$LEGACY_PATH" && ! -L "$LEGACY_PATH" ]]; then
  echo "Legacy path exists and is not a compatibility link: $LEGACY_PATH" >&2
  exit 1
fi

if [[ -L "$LEGACY_PATH" ]]; then
  rm "$LEGACY_PATH"
fi
ln -s "$CANONICAL_PATH" "$LEGACY_PATH"

if [[ -e "$LEGACY_ROOT_PATH" && ! -L "$LEGACY_ROOT_PATH" ]]; then
  echo "Legacy root path exists and is not a compatibility link: $LEGACY_ROOT_PATH" >&2
  exit 1
fi

if [[ -L "$LEGACY_ROOT_PATH" ]]; then
  rm "$LEGACY_ROOT_PATH"
fi
ln -s "$CANONICAL_PATH" "$LEGACY_ROOT_PATH"

git -C "$CANONICAL_PATH" remote set-url origin "$REPOSITORY_URL"
git -C "$CANONICAL_PATH" fetch origin --prune --tags

test "$(readlink -f "$LEGACY_PATH")" = "$CANONICAL_PATH"
test "$(readlink -f "$LEGACY_ROOT_PATH")" = "$CANONICAL_PATH"
test "$(git -C "$CANONICAL_PATH" remote get-url origin)" = "$REPOSITORY_URL"

echo "[migration] canonical=$CANONICAL_PATH legacy_links=$LEGACY_PATH,$LEGACY_ROOT_PATH repository=$REPOSITORY_URL"
