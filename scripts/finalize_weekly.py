"""
週次ダイジェストの後処理。

- data/judged.json の全id(低関連度も含む)を data/sent_ids.json に追記
  (同じ論文を来週また判定しないため)
- data/candidates.json を空にリセット(翌週分の蓄積を再開)
- data/judged.json を削除
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT_IDS_PATH = os.path.join(BASE_DIR, "data", "sent_ids.json")
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")


def main():
    sent_ids = set()
    if os.path.exists(SENT_IDS_PATH):
        with open(SENT_IDS_PATH, encoding="utf-8") as f:
            sent_ids = set(json.load(f))

    judged = []
    if os.path.exists(JUDGED_PATH):
        with open(JUDGED_PATH, encoding="utf-8") as f:
            judged = json.load(f)

    sent_ids.update(p["id"] for p in judged)
    with open(SENT_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(sent_ids), f, ensure_ascii=False, indent=2)

    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)

    if os.path.exists(JUDGED_PATH):
        os.remove(JUDGED_PATH)

    print(f"送信済みIDを更新しました(今回 {len(judged)} 件追加、累計 {len(sent_ids)} 件)")


if __name__ == "__main__":
    main()
