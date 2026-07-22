"""
Slackスレッドの最新の質問に1回だけ応答する、ステートレスな対話ハンドラ(クラウド用)。

Socket Mode常駐版(slack_agent.py)と違い、GitHub Actionsの使い捨て実行で動くことを想定。
claude のセッションはランナー間で永続しないため、--resume は使わず、
スレッド全体の会話履歴を毎回プロンプトに載せて文脈を再構築する。

呼び出し: repository_dispatch(slack_reply) から起動され、
環境変数 SLACK_CHANNEL / SLACK_THREAD_TS でスレッドを特定する。

必要な環境変数:
  SLACK_BOT_TOKEN          : xoxb- で始まるBot User OAuth Token
  SLACK_CHANNEL            : チャンネルID
  SLACK_THREAD_TS          : 対象スレッドの ts
  CLAUDE_CODE_OAUTH_TOKEN  : Claude Code CLI のサブスク認証トークン(claude が参照)
"""

import json
import os
import shutil
import subprocess
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREADS_PATH = os.path.join(BASE_DIR, "data", "slack_threads.json")
MODEL = os.environ.get("DIGEST_CLAUDE_MODEL", "sonnet")

SLACK_REPLIES_API = "https://slack.com/api/conversations.replies"
SLACK_POST_API = "https://slack.com/api/chat.postMessage"


def find_claude():
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    found = shutil.which("claude")
    if found:
        return found
    for cand in [
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]:
        if os.path.exists(cand):
            return cand
    sys.exit("claude CLI が見つかりません")


def fetch_thread(token, channel, thread_ts):
    resp = requests.get(
        SLACK_REPLIES_API,
        headers={"Authorization": f"Bearer {token}"},
        params={"channel": channel, "ts": thread_ts, "limit": 200},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        sys.exit(f"conversations.replies 失敗: {data.get('error')}")
    return data.get("messages", [])


def post_reply(token, channel, thread_ts, text):
    resp = requests.post(
        SLACK_POST_API,
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "thread_ts": thread_ts, "text": text, "unfurl_links": False},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        sys.exit(f"chat.postMessage 失敗: {data.get('error')}")


def build_prompt(paper, transcript):
    return f"""あなたはSlack上で研究者(恒星フレア研究が専門)と論文について議論するアシスタントです。
以下のスレッドの会話履歴を踏まえ、最後のユーザー発言に日本語で答えてください。

# 対象論文
- タイトル: {paper.get('title', '')}
- 日本語訳: {paper.get('title_ja', '')}
- 著者: {', '.join(paper.get('authors', [])[:10])}
- URL: {paper.get('url', '')}
- アブストラクト: {paper.get('abstract', '(なし)')}
- 要約: {paper.get('summary_ja', '')}

# これまでの会話(古い順)
{transcript}

# 回答スタイル
- 日本語で、Slackで読みやすい長さ(最大でも数段落)で答える
- 必要に応じて arxiv.org のページを WebFetch で参照してよい
- 論文本文にしか根拠がなく確認できない場合は、推測であることを明示する
- 出力は回答本文のみ(前置きや「回答:」などのラベルは不要)"""


def ask_claude(claude_bin, prompt):
    cmd = [
        claude_bin, "-p", "--model", MODEL, "--output-format", "json",
        "--allowedTools", "WebFetch(domain:arxiv.org)", prompt,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        return f"(エラー: claude実行に失敗しました: {res.stderr[:300]})"
    try:
        data = json.loads(res.stdout)
        return data.get("result", "").strip() or "(空の応答)"
    except json.JSONDecodeError:
        return res.stdout.strip()[:3000]


def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL")
    thread_ts = os.environ.get("SLACK_THREAD_TS")
    if not (token and channel and thread_ts):
        sys.exit("SLACK_BOT_TOKEN / SLACK_CHANNEL / SLACK_THREAD_TS が必要です")

    # このスレッドが「投稿された論文」のものか確認(そうでなければ何もしない)
    threads = {}
    if os.path.exists(THREADS_PATH):
        with open(THREADS_PATH, encoding="utf-8") as f:
            threads = json.load(f)
    if thread_ts not in threads:
        print(f"追跡対象外のスレッド({thread_ts})のため終了します")
        return
    paper = threads[thread_ts]

    messages = fetch_thread(token, channel, thread_ts)
    # 先頭(ルート=論文投稿)を除いた返信部分
    convo = messages[1:] if messages else []

    last_human = None
    last_bot_ts = 0.0
    for m in convo:
        if m.get("bot_id") or m.get("subtype"):
            last_bot_ts = max(last_bot_ts, float(m.get("ts", 0)))
        else:
            last_human = m

    if last_human is None:
        print("ユーザーの質問が見つからないため終了します")
        return
    # 直近のBot返信が最新の質問より後なら、既に回答済みとみなす(重複起動対策)
    if last_bot_ts > float(last_human["ts"]):
        print("既に回答済みのため終了します")
        return

    # 会話履歴を古い順にテキスト化(ルートの論文投稿は除外)
    lines = []
    for m in convo:
        speaker = "アシスタント" if (m.get("bot_id") or m.get("subtype")) else "ユーザー"
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    transcript = "\n".join(lines) if lines else "(なし)"

    claude_bin = find_claude()
    answer = ask_claude(claude_bin, build_prompt(paper, transcript))
    post_reply(token, channel, thread_ts, answer)
    print("スレッドに回答を投稿しました")


if __name__ == "__main__":
    main()
