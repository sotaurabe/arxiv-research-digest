#!/bin/bash
# 週次Slackダイジェストのオーケストレーション(launchdから毎週実行される想定)。
#
# 1. git pull で最新化
# 2. 直近8日分を追加取得(日次ジョブの取りこぼし対策。id単位で重複排除)
# 3. claude -p で関連度判定・翻訳・要約(Proプラン枠内、API課金なし)
# 4. 関連度が高い論文をSlackに投稿
# 5. sent_ids.json 更新・candidates.json リセット・push
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/weekly_digest.log"

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
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') 週次ダイジェスト開始 ====="

  if [ ! -f config/slack.env ]; then
    echo "config/slack.env がありません。config/slack.env.example を参考に作成してください"
    exit 1
  fi

  retry git pull --quiet origin main

  python3 -m venv .venv --upgrade-deps >/dev/null 2>&1 || true
  source .venv/bin/activate
  pip install -q requests feedparser

  ARXIV_LOOKBACK_DAYS=8 ARXIV_MAX_RESULTS=500 python3 scripts/fetch_candidates.py
  python3 scripts/judge_with_claude.py
  python3 scripts/post_slack_digest.py
  python3 scripts/finalize_weekly.py

  if ! git diff --quiet -- data/sent_ids.json data/candidates.json; then
    git add data/sent_ids.json data/candidates.json
    git commit -m "chore: weekly digest $(date '+%Y-%m-%d')"
    retry git push origin main
    echo "sent_ids.json / candidates.json をpushしました"
  fi

  echo "===== 週次ダイジェスト完了 ====="
} >> "$LOG_FILE" 2>&1
