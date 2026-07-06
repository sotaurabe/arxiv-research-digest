"""
data/candidates.json の論文を、ローカルの Claude Code CLI (`claude -p`) で
関連度判定・タイトル翻訳・日本語要約するスクリプト。

Anthropic API を直接叩かないため従量課金は発生せず、
Claude Pro/Max プランの利用枠内で動作します。

入力: data/candidates.json, config/research_profile.md
出力: data/judged.json (READMEのスキーマ準拠。全候補を含む)
"""

import json
import os
import re
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")
PROFILE_PATH = os.path.join(BASE_DIR, "config", "research_profile.md")
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")

CHUNK_SIZE = 25  # 1回のclaude呼び出しに載せる論文数
MODEL = os.environ.get("DIGEST_CLAUDE_MODEL", "sonnet")


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
    sys.exit(
        "claude CLI が見つかりません。https://claude.ai/install.sh でインストールし、"
        "`claude` でログインしてください(環境変数 CLAUDE_BIN でパス指定も可)"
    )


def build_prompt(profile: str, papers: list[dict]) -> str:
    papers_json = json.dumps(
        [{k: p[k] for k in ("id", "title", "abstract", "authors", "url")} for p in papers],
        ensure_ascii=False,
        indent=1,
    )
    return f"""あなたは研究論文の関連度判定を行うアシスタントです。
以下の研究プロファイルに照らして、論文リストの各論文を判定してください。

# 研究プロファイル
{profile}

# 論文リスト (JSON)
{papers_json}

# 指示
各論文について次のフィールドを持つJSONオブジェクトを作り、**全論文分**をJSON配列として出力してください。
- id, title, authors, url: 入力の値をそのままコピー
- relevance_score: 研究プロファイルとの関連度 (1-10の整数、10が最も関連が高い)
- reason: 判定理由 (日本語1文)
- title_ja: タイトルの日本語訳
- summary_ja: 200字程度の日本語要約 (何が新しいか、プロファイルとの関連を含める)

出力はJSON配列のみ。コードフェンスや説明文は一切付けないでください。"""


def parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    # コードフェンスが付いてしまった場合の保険
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSON配列が見つかりません: {text[:200]}")
    return json.loads(m.group(0))


def run_claude(claude_bin: str, prompt: str) -> list[dict]:
    cmd = [claude_bin, "-p", "--model", MODEL, "--output-format", "json", prompt]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if res.returncode != 0:
        raise RuntimeError(f"claude実行失敗 (exit {res.returncode}): {res.stderr[:500]}")
    outer = json.loads(res.stdout)
    return parse_json_array(outer.get("result", ""))


def main():
    if not os.path.exists(CANDIDATES_PATH):
        sys.exit(f"{CANDIDATES_PATH} がありません。先に fetch_candidates.py を実行してください")
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)
    if not candidates:
        print("候補が0件のため、判定をスキップします")
        with open(JUDGED_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = f.read()

    claude_bin = find_claude()
    judged: list[dict] = []
    chunks = [candidates[i : i + CHUNK_SIZE] for i in range(0, len(candidates), CHUNK_SIZE)]
    for i, chunk in enumerate(chunks, 1):
        print(f"判定中 {i}/{len(chunks)} ({len(chunk)}件)...")
        prompt = build_prompt(profile, chunk)
        try:
            results = run_claude(claude_bin, prompt)
        except (ValueError, json.JSONDecodeError):
            print("  JSON解析に失敗。1回だけリトライします")
            results = run_claude(claude_bin, prompt + "\n\n重要: 出力はJSON配列のみとすること。")
        judged.extend(results)

    with open(JUDGED_PATH, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, indent=2)
    high = [p for p in judged if p.get("relevance_score", 0) >= 8]
    print(f"判定完了: {len(judged)}件 (うち関連度8以上 {len(high)}件) → {JUDGED_PATH}")


if __name__ == "__main__":
    main()
