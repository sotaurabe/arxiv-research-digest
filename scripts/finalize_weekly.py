"""
週次ダイジェストの後処理。

- data/judged.json のうち、実際にSlackへ通知した(関連度が閾値以上の)IDだけを
  data/sent_ids.json に追記する(同じ論文を二重通知しないため)。
  閾値未満の論文はここに記録しない — arXiv側の取得期間(ARXIV_LOOKBACK_DAYS)が
  尽きるまで、次回以降の実行でも再度候補として取得・判定される。
- data/candidates.json を空にリセット(翌週分の蓄積を再開)
- data/judged.json を削除
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT_IDS_PATH = os.path.join(BASE_DIR, "data", "sent_ids.json")
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")
# post_slack_digest.py と同じ既定値・同じ環境変数を参照する
RELEVANCE_THRESHOLD = int(os.environ.get("RELEVANCE_THRESHOLD", "8"))


def main():
    sent_ids = set()
    if os.path.exists(SENT_IDS_PATH):
        with open(SENT_IDS_PATH, encoding="utf-8") as f:
            sent_ids = set(json.load(f))

    judged = []
    if os.path.exists(JUDGED_PATH):
        with open(JUDGED_PATH, encoding="utf-8") as f:
            judged = json.load(f)

    notified = [p for p in judged if p.get("relevance_score", 0) >= RELEVANCE_THRESHOLD]
    sent_ids.update(p["id"] for p in notified)
    with open(SENT_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(sent_ids), f, ensure_ascii=False, indent=2)

    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)

    if os.path.exists(JUDGED_PATH):
        os.remove(JUDGED_PATH)

    print(
        f"送信済みIDを更新しました(今回 {len(notified)} 件追加、累計 {len(sent_ids)} 件。"
        f"閾値未満だった {len(judged) - len(notified)} 件は次回以降も候補として残ります)"
    )


if __name__ == "__main__":
    main()
