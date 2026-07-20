"""
Slackスレッドで論文について対話するAIエージェント。

仕組み:
- Socket Mode で常駐(公開エンドポイント不要。ローカルMacで動く)
- post_slack_digest.py が投稿した論文メッセージのスレッドに誰かが返信すると、
  その論文のメタデータ(タイトル・アブストラクト等)を文脈に載せて
  ローカルの Claude Code CLI (`claude -p`) に質問を渡し、回答をスレッドに投稿する
- スレッドごとに claude のセッションIDを保持し、会話の文脈を継続する
- LLM呼び出しはProプラン枠内(API従量課金なし)

必要な環境変数 (config/slack.env):
  SLACK_BOT_TOKEN : xoxb-...
  SLACK_APP_TOKEN : xapp-... (Socket Mode用App-Level Token)
"""

# macOS標準のPython 3.9では `str | None` 記法が実行時エラーになるため、
# 型注釈の評価を遅延させる(3.7+で有効)
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREADS_PATH = os.path.join(BASE_DIR, "data", "slack_threads.json")
SESSIONS_PATH = os.path.join(BASE_DIR, "data", "slack_sessions.json")
MODEL = os.environ.get("DIGEST_CLAUDE_MODEL", "sonnet")


def load_slack_env():
    env_path = os.path.join(BASE_DIR, "config", "slack.env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_slack_env()

from slack_bolt import App  # noqa: E402
from slack_bolt.adapter.socket_mode import SocketModeHandler  # noqa: E402

app = App(token=os.environ["SLACK_BOT_TOKEN"])


def find_claude() -> str:
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


CLAUDE_BIN = find_claude()


def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: str, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def first_prompt(paper: dict, question: str) -> str:
    return f"""あなたはSlack上で研究者(恒星フレア研究が専門)と論文について議論するアシスタントです。

# 対象論文
- タイトル: {paper['title']}
- 日本語訳: {paper.get('title_ja', '')}
- 著者: {', '.join(paper.get('authors', [])[:10])}
- URL: {paper.get('url', '')}
- アブストラクト: {paper.get('abstract', '(なし)')}
- 要約: {paper.get('summary_ja', '')}

# 回答スタイル
- 日本語で、Slackで読みやすい長さ(最大でも数段落)で答える
- 必要に応じて arxiv.org のページを WebFetch で参照してよい
- 根拠が論文本文にしかなく確認できない場合は、推測であることを明示する

# 質問
{question}"""


def ask_claude(prompt: str, session_id: str | None) -> tuple[str, str | None]:
    cmd = [CLAUDE_BIN, "-p", "--model", MODEL, "--output-format", "json",
           "--allowedTools", "WebFetch(domain:arxiv.org)"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        return f"(エラー: claude実行に失敗しました: {res.stderr[:300]})", session_id
    try:
        data = json.loads(res.stdout)
        return data.get("result", "").strip() or "(空の応答)", data.get("session_id", session_id)
    except json.JSONDecodeError:
        return res.stdout.strip()[:3000], session_id


@app.event("message")
def handle_message(event, say, client):
    # bot自身の発言・編集イベントなどは無視
    if event.get("bot_id") or event.get("subtype"):
        return
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return
    threads = load_json(THREADS_PATH, {})
    if thread_ts not in threads:
        return

    channel = event["channel"]
    # 処理中であることをリアクションで示す(失敗しても続行)
    try:
        client.reactions_add(channel=channel, timestamp=event["ts"], name="thinking_face")
    except Exception:
        pass

    paper = threads[thread_ts]
    sessions = load_json(SESSIONS_PATH, {})
    session_id = sessions.get(thread_ts)

    if session_id:
        prompt = event["text"]
    else:
        prompt = first_prompt(paper, event["text"])

    answer, new_session = ask_claude(prompt, session_id)
    if new_session:
        sessions[thread_ts] = new_session
        save_json(SESSIONS_PATH, sessions)

    say(text=answer, thread_ts=thread_ts)
    try:
        client.reactions_remove(channel=channel, timestamp=event["ts"], name="thinking_face")
    except Exception:
        pass


if __name__ == "__main__":
    print("Slack論文エージェントを起動します (Socket Mode)")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
