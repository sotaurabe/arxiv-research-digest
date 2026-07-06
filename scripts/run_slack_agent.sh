#!/bin/bash
# Slack対話エージェントの起動ラッパー(launchdで常駐させる想定)。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -f config/slack.env ]; then
  echo "config/slack.env がありません。config/slack.env.example を参考に作成してください" >&2
  exit 1
fi

python3 -m venv .venv --upgrade-deps >/dev/null 2>&1 || true
source .venv/bin/activate
pip install -q slack_bolt requests

exec python3 scripts/slack_agent.py
