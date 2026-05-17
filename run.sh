#!/usr/bin/env bash
# run.sh — Cron entrypoint for the Research Radar pipeline.
#
# Usage:
#   ./run.sh              # Run as scheduled
#   ./run.sh manual       # Run manually
#   ./run.sh relink       # Rescore/rebuild/refresh relationships, no fetch
#   ./run.sh reanalyze    # Regenerate summaries/analysis/notes, no fetch
#
# Cron example (daily at 1am):
#   0 1 * * * /path/to/research-radar/run.sh scheduled >> /path/to/research-radar/data/cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source ".env"
    set +a
fi

RUN_TYPE="${1:-scheduled}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL%/}"

echo "────────────────────────────────────────"
echo "Research Radar Pipeline"
echo "Run type: $RUN_TYPE"
echo "Time: $(date -Iseconds)"
echo "────────────────────────────────────────"

# Check if Ollama is running
OLLAMA_STARTED_BY_US=0
OLLAMA_PID=""

cleanup() {
    if [ "$OLLAMA_STARTED_BY_US" -eq 1 ] && [ -n "$OLLAMA_PID" ] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
        echo "Shutting down Ollama daemon..."
        kill "$OLLAMA_PID"
    fi
}
trap cleanup EXIT

ollama_ready() {
    curl -fsS --connect-timeout 2 --max-time 5 "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1
}

if ! ollama_ready; then
    case "$OLLAMA_BASE_URL" in
        http://localhost:*|http://127.0.0.1:*)
            echo "Starting Ollama daemon..."
            ollama serve >/dev/null 2>&1 &
            OLLAMA_PID=$!
            OLLAMA_STARTED_BY_US=1

            echo "Waiting for Ollama to become responsive..."
            for _ in $(seq 1 60); do
                if ollama_ready; then
                    echo "Ollama is ready."
                    break
                fi
                if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
                    echo "Ollama daemon exited before becoming ready."
                    exit 1
                fi
                sleep 1
            done
            if ! ollama_ready; then
                echo "Timed out waiting for Ollama at $OLLAMA_BASE_URL"
                exit 1
            fi
            ;;
        *)
            echo "Ollama is not reachable at $OLLAMA_BASE_URL"
            echo "Start Ollama there or update OLLAMA_BASE_URL in .env."
            exit 1
            ;;
    esac
fi

if [ "$RUN_TYPE" = "relink" ] || [ "$RUN_TYPE" = "reanalyze" ]; then
    python -m src.maintenance "$RUN_TYPE"
else
    python -m src.main "$RUN_TYPE"
fi

echo "────────────────────────────────────────"
echo "Pipeline finished at $(date -Iseconds)"
echo "────────────────────────────────────────"
