"""
data/judged.json のうち関連度が閾値以上の論文をSlackチャンネルに投稿するスクリプト。

- 週次サマリを1件投稿し、続けて論文ごとに1メッセージずつ投稿する
  (論文ごとのスレッドでAIエージェントと議論できるようにするため)
- 投稿したメッセージのts→論文情報の対応を data/slack_threads.json に保存する
  (slack_agent.py がスレッド返信に応答する際の文脈として使う)

必要な環境変数 (config/slack.env から読み込み):
  SLACK_BOT_TOKEN  : xoxb- で始まるBot User OAuth Token
  SLACK_CHANNEL_ID : 投稿先チャンネルID (C0123... 形式)
"""

import json
import os
import sys
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")
THREADS_PATH = os.path.join(BASE_DIR, "data", "slack_threads.json")

RELEVANCE_THRESHOLD = int(os.environ.get("RELEVANCE_THRESHOLD", "8"))
SLACK_API = "https://slack.com/api/chat.postMessage"


def load_slack_env():
    env_path = os.path.join(BASE_DIR, "config", "slack.env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def post_message(token: str, channel: str, text: str) -> str:
    resp = requests.post(
        SLACK_API,
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": text, "unfurl_links": False},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack投稿失敗: {data.get('error')}")
    return data["ts"]


def main():
    load_slack_env()
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        sys.exit("SLACK_BOT_TOKEN / SLACK_CHANNEL_ID が未設定です (config/slack.env を確認)")

    with open(JUDGED_PATH, encoding="utf-8") as f:
        judged = json.load(f)

    # エージェント用にアブストラクトを候補ファイルから引けるようにしておく
    abstracts = {}
    if os.path.exists(CANDIDATES_PATH):
        with open(CANDIDATES_PATH, encoding="utf-8") as f:
            abstracts = {p["id"]: p.get("abstract", "") for p in json.load(f)}

    relevant = sorted(
        [p for p in judged if p.get("relevance_score", 0) >= RELEVANCE_THRESHOLD],
        key=lambda x: -x["relevance_score"],
    )
    today = datetime.now().strftime("%Y-%m-%d")

    if not relevant:
        post_message(
            token, channel,
            f":books: 今週の論文ダイジェスト ({today})\n"
            f"判定 {len(judged)}件のうち、関連度{RELEVANCE_THRESHOLD}以上の論文はありませんでした。",
        )
        print("関連論文なしの旨を投稿しました")
        return

    post_message(
        token, channel,
        f":books: *今週の関連論文ダイジェスト ({today})*\n"
        f"判定 {len(judged)}件 → 関連度{RELEVANCE_THRESHOLD}以上 *{len(relevant)}件* :point_down:",
    )

    threads = {}
    if os.path.exists(THREADS_PATH):
        with open(THREADS_PATH, encoding="utf-8") as f:
            threads = json.load(f)

    for p in relevant:
        text = (
            f"*{p['title_ja']}*\n"
            f"原題: {p['title']}\n"
            f"著者: {', '.join(p['authors'][:6])}\n"
            f"関連度: *{p['relevance_score']}/10* — {p['reason']}\n"
            f"{p['url']}\n\n"
            f"{p['summary_ja']}\n\n"
            f"_:speech_balloon: このスレッドに返信すると、AIエージェントと議論できます_"
        )
        ts = post_message(token, channel, text)
        threads[ts] = {
            "id": p["id"],
            "title": p["title"],
            "title_ja": p["title_ja"],
            "authors": p["authors"],
            "url": p["url"],
            "summary_ja": p["summary_ja"],
            "abstract": abstracts.get(p["id"], ""),
        }

    with open(THREADS_PATH, "w", encoding="utf-8") as f:
        json.dump(threads, f, ensure_ascii=False, indent=2)
    print(f"{len(relevant)}件をSlackに投稿し、スレッド対応表を更新しました")


if __name__ == "__main__":
    main()
