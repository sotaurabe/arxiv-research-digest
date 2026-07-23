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
import sys

from claude_cli import find_claude, run_claude_text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES_PATH = os.path.join(BASE_DIR, "data", "candidates.json")
PROFILE_PATH = os.path.join(BASE_DIR, "config", "research_profile.md")
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")

CHUNK_SIZE = 25  # 1回のclaude呼び出しに載せる論文数
MODEL = os.environ.get("DIGEST_CLAUDE_MODEL", "sonnet")
# 通知閾値。実際の通知判定は post_slack_digest.py 側で行うが、
# ログの件数表示を実運用の閾値と揃えるためここでも参照する。
RELEVANCE_THRESHOLD = int(os.environ.get("RELEVANCE_THRESHOLD", "8"))


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
    return parse_json_array(run_claude_text(prompt, model=MODEL, claude_bin=claude_bin))


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
    high = [p for p in judged if p.get("relevance_score", 0) >= RELEVANCE_THRESHOLD]
    print(
        f"判定完了: {len(judged)}件 "
        f"(うち関連度{RELEVANCE_THRESHOLD}以上 {len(high)}件) → {JUDGED_PATH}"
    )


if __name__ == "__main__":
    main()
