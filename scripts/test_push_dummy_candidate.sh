#!/bin/bash
# ローカルfetch→pushの仕組みをテストするためのダミーデータ投入スクリプト。
# 実際のarXiv取得は行わず、テスト用のダミー候補を1件 data/candidates.json に書き込み、
# commit & push まで通るかどうかだけを確認する。動作確認用なので、
# 確認が終わったら次回の本番fetch(local_fetch_and_push.sh)で上書きされる。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

git pull --quiet origin main

cat > data/candidates.json <<'EOF'
[
  {
    "id": "0000.00000",
    "title": "A Dummy Test Paper for Push Pipeline Verification",
    "abstract": "This is a dummy candidate entry used only to verify that the local fetch-and-push pipeline correctly commits and pushes data/candidates.json to the repository. It is not a real arXiv paper and has deliberately low relevance.",
    "authors": ["Test Author"],
    "url": "https://arxiv.org/abs/0000.00000"
  }
]
EOF

git add data/candidates.json
git commit -m "test: verify local fetch/push pipeline with a dummy low-relevance candidate"
git push origin main

echo "ダミー候補をpushしました。GitHub上で data/candidates.json の内容を確認してください。"
echo "確認が終わったら、次回 local_fetch_and_push.sh を実行すれば実際のfetch結果で上書きされます。"
