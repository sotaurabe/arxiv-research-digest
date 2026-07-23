"""
arXiv新着論文の取得 + 重複排除のみを行うスクリプト。

このスクリプトは Anthropic API を一切呼び出しません(=課金が発生しません)。
関連度判定・要約・翻訳は、このスクリプトの出力(data/candidates.json)を
Claude Code(ルーティン実行中のエージェント自身)が読んで行う想定です。

出力: data/candidates.json
  [
    {"id": ..., "title": ..., "abstract": ..., "authors": [...], "url": ...},
    ...
  ]
"""

import json
import os
from datetime import datetime, timedelta, timezone

import feedparser
import requests

ARXIV_CATEGORIES = ["astro-ph.SR", "astro-ph.HE"]
LOOKBACK_DAYS = int(os.environ.get("ARXIV_LOOKBACK_DAYS", "1"))
MAX_RESULTS = int(os.environ.get("ARXIV_MAX_RESULTS", "150"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT_IDS_PATH = os.path.join(BASE_DIR, "data", "sent_ids.json")
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")

ARXIV_API_URL = "http://export.arxiv.org/api/query"


def load_sent_ids() -> set:
    if not os.path.exists(SENT_IDS_PATH):
        return set()
    with open(SENT_IDS_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def fetch_recent_papers() -> list[dict]:
    # 区切りは半角スペースにする。"+OR+" と書くと requests が "+" を %2B に
    # エンコードし、arXiv 側でクエリが壊れて常に0件になる
    category_query = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    params = {
        "search_query": category_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": MAX_RESULTS,
    }
    resp = requests.get(ARXIV_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    papers = []
    for entry in feed.entries:
        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published < cutoff:
            continue
        arxiv_id = entry.id.split("/abs/")[-1]
        papers.append(
            {
                "id": arxiv_id,
                "title": " ".join(entry.title.split()),
                "abstract": " ".join(entry.summary.split()),
                "authors": [a.name for a in entry.authors],
                "url": entry.id,
            }
        )
    return papers


def load_existing_candidates() -> list[dict]:
    if not os.path.exists(CANDIDATES_PATH):
        return []
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def main():
    sent_ids = load_sent_ids()
    papers = fetch_recent_papers()

    # 週次でまとめて判定する運用のため、日々の取得分は既存の候補に追記して蓄積する
    existing = load_existing_candidates()
    known_ids = {p["id"] for p in existing} | sent_ids
    added = [p for p in papers if p["id"] not in known_ids]
    candidates = existing + added

    os.makedirs(os.path.dirname(CANDIDATES_PATH), exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"新着 {len(papers)} 件中、新規候補 {len(added)} 件を追加(累計 {len(candidates)} 件)→ {CANDIDATES_PATH}")
    if candidates:
        print("\n次のステップ: config/research_profile.md と照らして各論文の関連度を判定し、")
        print("data/judged.json に結果を書き出してください(スキーマはREADME参照)。")
    else:
        print("候補がないため、ここで終了して問題ありません。")


if __name__ == "__main__":
    main()
