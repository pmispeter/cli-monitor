#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_NAME="cli-monitor"
MARKER_BEGIN="# >>> cli-monitor wrappers >>>"
MARKER_END="# <<< cli-monitor wrappers <<<"

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'setup.sh: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    require_command sudo
    sudo "$@"
  fi
}

install_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    return
  fi

  if command -v brew >/dev/null 2>&1; then
    log "Installing Python app installer: pipx"
    brew install pipx
    return
  fi

  fail "missing required command: pipx. Install pipx with your system package manager and rerun setup.sh."
}

install_system_dependencies() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    local packages=()

    if ! command -v pipx >/dev/null 2>&1; then
      packages+=(pipx)
    fi

    if ! command -v xdotool >/dev/null 2>&1; then
      packages+=(xdotool)
    fi
    if ! command -v xprop >/dev/null 2>&1; then
      packages+=(x11-utils)
    fi

    if [[ "${#packages[@]}" -eq 0 ]]; then
      return
    fi

    log "Installing setup dependencies: ${packages[*]}"
    run_privileged apt-get update
    run_privileged apt-get install -y "${packages[@]}"
    return
  fi

  if ! command -v pipx >/dev/null 2>&1; then
    fail "missing required command: pipx. Install pipx with your system package manager and rerun setup.sh."
  fi

  if command -v xdotool >/dev/null 2>&1 &&
    command -v xprop >/dev/null 2>&1; then
    return
  fi

  log "Window focus helpers are missing. Install xdotool and xprop with your system package manager."
}

detect_rc_file() {
  case "$(uname -s)" in
    Darwin)
      printf '%s\n' "${HOME}/.zshrc"
      ;;
    Linux)
      printf '%s\n' "${HOME}/.bashrc"
      ;;
    *)
      fail "unsupported OS: $(uname -s). Expected Linux or macOS."
      ;;
  esac
}

resolve_command() {
  local name="$1"
  local path

  path="$(command -v "$name" 2>/dev/null || true)"
  if [[ -n "$path" && "$path" != "$HOME/.local/bin/$PACKAGE_NAME" ]]; then
    printf '%s\n' "$path"
  fi
}

install_with_pipx() {
  require_command pipx

  log "Installing ${PACKAGE_NAME} with pipx from ${PROJECT_DIR}"
  pipx install --force --editable "$PROJECT_DIR"
}

resolve_cli_monitor() {
  local path

  path="$(command -v cli-monitor 2>/dev/null || true)"
  if [[ -n "$path" ]]; then
    printf '%s\n' "$path"
    return
  fi

  path="${HOME}/.local/bin/cli-monitor"
  if [[ -x "$path" ]]; then
    printf '%s\n' "$path"
    return
  fi

  fail "cli-monitor was installed, but its executable was not found. Check pipx output and PATH."
}

rc_file_has_wrapper() {
  local rc_file="$1"

  [[ -f "$rc_file" ]] && {
    grep -Fq "$MARKER_BEGIN" "$rc_file" || grep -Fq "cli-monitor run --" "$rc_file"
  }
}

append_rc_wrappers() {
  local rc_file="$1"
  local cli_monitor_bin="$2"
  local codex_bin="$3"
  local claude_bin="$4"

  touch "$rc_file"

  if rc_file_has_wrapper "$rc_file"; then
    log "${rc_file} already contains a cli-monitor wrapper; leaving it unchanged."
    return
  fi

  if [[ -z "$codex_bin" && -z "$claude_bin" ]]; then
    log "No codex or claude executable found in PATH; no wrappers were added to ${rc_file}."
    return
  fi

  {
    printf '\n%s\n' "$MARKER_BEGIN"
    printf 'CLI_MONITOR_BIN=%q\n' "$cli_monitor_bin"
    if [[ -n "$codex_bin" ]]; then
      printf 'CODEX_BIN=%q\n' "$codex_bin"
      printf 'codex() {\n'
      printf '  "$CLI_MONITOR_BIN" run -- "$CODEX_BIN" "$@"\n'
      printf '}\n'
    fi
    if [[ -n "$claude_bin" ]]; then
      printf 'CLAUDE_BIN=%q\n' "$claude_bin"
      printf 'claude() {\n'
      printf '  "$CLI_MONITOR_BIN" run -- "$CLAUDE_BIN" "$@"\n'
      printf '}\n'
    fi
    printf '%s\n' "$MARKER_END"
  } >>"$rc_file"

  log "Added cli-monitor wrappers to ${rc_file}."
}

main() {
  local rc_file
  local codex_bin=""
  local claude_bin=""
  local cli_monitor_bin

  rc_file="$(detect_rc_file)"
  codex_bin="$(resolve_command codex)"
  claude_bin="$(resolve_command claude)"

  install_system_dependencies
  install_pipx
  install_with_pipx
  cli_monitor_bin="$(resolve_cli_monitor)"
  append_rc_wrappers "$rc_file" "$cli_monitor_bin" "$codex_bin" "$claude_bin"

  log "Done. Open a new shell or run: source ${rc_file}"
}

main "$@"
