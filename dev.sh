#!/usr/bin/env bash
# Run the personal workspace. No containers, accounts, or cloud calls at startup.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  printf '%s\n' 'Usage: ./dev.sh [--setup | --help]' \
    '  (no arguments)  Start the local API and web app; Ctrl+C stops both.' \
    '  --setup         Install locked Python/Node dependencies, then exit.'
}

case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --setup|'') ;;
  *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

for command in uv npm; do
  command -v "$command" >/dev/null || {
    printf 'Missing %s. Install it before running ./dev.sh.\n' "$command" >&2
    exit 1
  }
done
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

if [[ "${1:-}" == --setup ]]; then
  uv sync --frozen --group dev --group web
  (cd frontend && npm ci)
  printf '\nSetup complete. Optionally copy .env.example to .env, then run ./dev.sh.\n'
  exit 0
fi

command -v curl >/dev/null || { printf 'curl is required for startup health checks.\n' >&2; exit 1; }
if [[ ! -d .venv || ! -x frontend/node_modules/.bin/next ]]; then
  printf 'Dependencies are missing. Run ./dev.sh --setup first.\n' >&2
  exit 1
fi

# Fail before starting either process rather than attaching to another app.
uv run --no-sync python - <<'PY'
import socket
import sys
for port in (8000, 3000):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Port {port} is unavailable. Stop its owner before running ./dev.sh.")
PY

# Job-control process groups let cleanup stop uv/npm and their descendants,
# without killing other servers belonging to the user.
set -m
pids=()
cleanup() {
  status=$?
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uv run --no-sync uvicorn northwind_copilot.web.app:app \
  --host 127.0.0.1 --port 8000 --reload &
pids+=("$!")

wait_ready() {
  local url="$1" pid="$2" label="$3"
  for ((attempt=0; attempt<120; attempt++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '%s exited during startup; see its logs above.\n' "$label" >&2
      return 1
    fi
    if curl --noproxy '*' --fail --silent --output /dev/null \
      --connect-timeout 1 --max-time 2 "$url"; then return 0; fi
    sleep 1
  done
  printf '%s did not become ready within the startup window.\n' "$label" >&2
  return 1
}
wait_ready http://127.0.0.1:8000/api/health "${pids[0]}" Backend

(cd frontend && exec env NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 \
  npm run dev -- --hostname 127.0.0.1) &
pids+=("$!")
wait_ready http://127.0.0.1:3000 "${pids[1]}" Frontend
printf '\nNorthwind Copilot: http://127.0.0.1:3000\nCtrl+C stops both servers.\n\n'

# Portable to macOS's Bash as well as Linux (no wait -n dependency).
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do
  sleep 1
done
printf 'A server stopped; shutting down the other server.\n' >&2
exit 1
