#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="${ROOT_DIR}/agent-IA-paul/urd-verifier-agent"
PYTHON_BIN="${AGENT_DIR}/.venv/bin/python3"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Environnement Python introuvable: ${PYTHON_BIN}" >&2
  exit 1
fi

export PORT="${PORT:-8000}"
export URD_STATIC_UI_DIR="${ROOT_DIR}"

echo "Lancement de Tickmark + urd-verifier-agent sur http://localhost:${PORT}"
cd "${AGENT_DIR}"
exec "${PYTHON_BIN}" -m uvicorn urd_verifier.api.main:app --host 0.0.0.0 --port "${PORT}"
