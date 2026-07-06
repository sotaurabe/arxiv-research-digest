#!/bin/bash
# arXiv新着の取得だけをローカルで実行し、data/candidates.json をリポジトリにpushする。
# Claude Code ルーティン側はこの後 `git pull` して candidates.json を読むだけでよい
# (routine 環境からは export.arxiv.org への通信がブロックされているため)。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/local_fetch.log"

cd "$REPO_DIR"

# スリープ復帰直後などネットワーク未接続のタイミングに備えたリトライ
retry() {
  local i
  for i in 1 2 3; do
    "$@" && return 0
    echo "失敗したため30秒後にリトライします ($i/3): $*"
    sleep 30
  done
  "$@"
}

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="

  retry git pull --quiet origin main

  python3 -m venv .venv --upgrade-deps >/dev/null 2>&1 || true
  source .venv/bin/activate
  pip install -q requests feedparser

  # 取りこぼし防止のため2日分見る(重複はid単位で排除されるので安全)
  ARXIV_LOOKBACK_DAYS=2 python3 scripts/fetch_candidates.py

  if ! git diff --quiet -- data/candidates.json; then
    git add data/candidates.json
    git commit -m "chore: update candidates.json ($(date '+%Y-%m-%d'))"
    retry git push origin main
    echo "candidates.json を更新してpushしました"
  else
    echo "candidates.json に変更なし(新着候補なし、または既にpush済み)"
  fi
} >> "$LOG_FILE" 2>&1
