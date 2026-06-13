#!/usr/bin/env bash
set -euo pipefail

repo_path="${REPO_PATH:-$(pwd)}"
base_ref="${BASE_REF:-main}"
reports_dir="${REPORTS_DIR:-/home/ubuntu/amx/reports}"
refresh_if_stale="${REFRESH_IF_STALE:-0}"
skip_detect_changes="${SKIP_DETECT_CHANGES:-0}"

if [[ ! -d "$repo_path/.git" ]]; then
  echo "Repository path must be a git checkout: $repo_path" >&2
  exit 1
fi

command -v git >/dev/null || {
  echo "git is required" >&2
  exit 1
}

command -v gitnexus >/dev/null || {
  echo "gitnexus is required" >&2
  exit 1
}

mkdir -p "$reports_dir"
timestamp="$(date -u +%Y%m%d-%H%M%S)"
report_path="$reports_dir/agent-collaboration-health-$timestamp.md"

cd "$repo_path"

{
  echo "# Agent Collaboration Health"
  echo
  echo "- Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- Repository: $repo_path"
  echo "- Base ref: $base_ref"
  echo
  echo "## Workspace Layout"
  echo
  for path in \
    "/home/ubuntu/amx/production/AMX" \
    "/home/ubuntu/amx/staging" \
    "/home/ubuntu/amx/gitnexus" \
    "/home/ubuntu/amx/reports"; do
    if [[ -e "$path" ]]; then
      echo "- [OK] $path"
    else
      echo "- [MISSING] $path"
    fi
  done
  echo

  run_section() {
    local title="$1"
    shift
    echo "## $title"
    echo
    echo '```text'
    "$@" 2>&1 || true
    echo '```'
    echo
  }

  run_section "Git Branch" git branch --show-current
  run_section "Git Commit" git log -1 --oneline
  run_section "Git Status" git status -sb
  run_section "GitNexus Version" gitnexus --version
  run_section "GitNexus Status" gitnexus status

  if [[ "$refresh_if_stale" == "1" ]] && ! gitnexus status 2>&1 | grep -q "up-to-date"; then
    run_section "GitNexus Refresh" gitnexus analyze --index-only
    run_section "GitNexus Status After Refresh" gitnexus status
  fi

  if [[ "$skip_detect_changes" != "1" ]]; then
    run_section "GitNexus Detect Changes" gitnexus detect-changes --scope all --base-ref "$base_ref"
  fi
} > "$report_path"

echo "Collaboration health report written to $report_path"
