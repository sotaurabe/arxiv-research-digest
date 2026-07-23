"""
研究プロファイル生成スクリプト

Semantic Scholar から著者の過去論文(タイトル・アブストラクト)を取得し、
Claude にそれらを読ませて「研究プロファイル(テーマ・キーワード・問題設定)」を
自然文で生成させる。生成結果は config/research_profile.md に保存され、
judge_with_claude.py / daily_digest.py が関連度判定の "ものさし" として利用する。

実行エンジンは2通り:
  cli (既定) : Claude Code CLI (`claude -p`) を使う。サブスク枠で動くため課金なし。
               GitHub Actions では CLAUDE_CODE_OAUTH_TOKEN が使われる。
  api        : Anthropic API を直接叩く。ANTHROPIC_API_KEY が必要で従量課金が発生する。

使い方:
    python scripts/build_profile.py --author-name "Sota Urabe" \
        --extra-text-file config/thesis_summary_ja.txt

通常は GitHub Actions の "Update Research Profile" ワークフローから実行し、
差分をプルリクエストでレビューしてから反映する。
"""

# macOS標準のPython 3.9では `str | None` 記法が実行時エラーになるため、
# 型注釈の評価を遅延させる(3.7+で有効)
from __future__ import annotations

import argparse
import os
import sys

import requests

from claude_cli import DEFAULT_MODEL, has_claude, run_claude_text

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/author/search"
SEMANTIC_SCHOLAR_PAPERS_URL = "https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
API_MODEL = "claude-sonnet-4-6"

# プロンプト肥大化(=コマンドライン長の上限)を避けるための上限
MAX_PAPERS = 60
MAX_ABSTRACT_CHARS = 2000
MAX_EXTRA_CHARS = 8000

# 生成物が壊れていないかの最低限のチェック
MIN_PROFILE_CHARS = 300
REQUIRED_HEADINGS = ["## 主要な研究テーマ", "## 関連キーワード", "## 関連度が高い/低いの目安"]

HEADER = """# 研究プロファイル

<!-- このファイルは scripts/build_profile.py が自動生成します。
     手で編集しても構いませんが、次回の自動生成で上書きされます。
     恒久的に反映したい内容は config/thesis_summary_ja.txt 側に追記してください。
     更新履歴は git log を参照。 -->

このファイルは judge_with_claude.py / daily_digest.py が新着論文の関連度を
判定する際の「ものさし」として使われます。

"""


def find_author_id(author_name: str) -> str:
    """著者名から Semantic Scholar の author_id を検索する。複数ヒットした場合は先頭候補を採用。"""
    resp = requests.get(
        SEMANTIC_SCHOLAR_SEARCH_URL,
        params={"query": author_name},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("data", [])
    if not candidates:
        raise RuntimeError(f"著者 '{author_name}' が Semantic Scholar 上に見つかりませんでした")

    if len(candidates) > 1:
        print(f"[注意] 同姓同名候補が {len(candidates)} 件見つかりました。先頭候補を使用します:")
        for c in candidates[:5]:
            print(f"  - {c['name']} (authorId={c['authorId']}, papers={c.get('paperCount', '?')})")

    return candidates[0]["authorId"]


def fetch_papers(author_id: str) -> list[dict]:
    """著者の論文一覧(タイトル・アブストラクト・年)を新しい順に取得する。"""
    resp = requests.get(
        SEMANTIC_SCHOLAR_PAPERS_URL.format(author_id=author_id),
        params={"fields": "title,abstract,year,externalIds"},
        timeout=30,
    )
    resp.raise_for_status()
    papers = [p for p in resp.json().get("data", []) if p.get("abstract")]
    # 新しい論文ほどプロファイルへの寄与を大きくしたいので、年の降順で上限まで採用
    papers.sort(key=lambda p: p.get("year") or 0, reverse=True)
    if len(papers) > MAX_PAPERS:
        print(f"[情報] 論文が {len(papers)} 件あるため、新しい順に {MAX_PAPERS} 件のみ使用します")
        papers = papers[:MAX_PAPERS]
    return papers


def load_extra_text(path: str | None) -> str:
    """修士論文などの追加テキストファイルがあれば読み込む(任意)。"""
    if not path:
        return ""
    if not os.path.exists(path):
        print(f"[警告] 追加テキストファイルが見つかりません: {path}")
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_prompt(papers: list[dict], extra_text: str) -> str:
    papers_block = "\n\n".join(
        f"タイトル: {p['title']}\n年: {p.get('year', '不明')}\n"
        f"アブストラクト: {p['abstract'][:MAX_ABSTRACT_CHARS]}"
        for p in papers
    )
    extra_block = (
        f"\n\n### 追加参考資料(修士論文など)からの抜粋\n{extra_text[:MAX_EXTRA_CHARS]}"
        if extra_text
        else ""
    )

    return f"""あなたは研究者の興味・専門性を分析するアシスタントです。
以下は、ある研究者の過去の発表論文のタイトルとアブストラクトです。
これらを読んで、この研究者の「研究プロファイル」を日本語で作成してください。

出力は必ず次の4つの見出しをこの順序・この表記で含むMarkdownにしてください。

## 主要な研究テーマ
2〜4個程度を箇条書き。

## よく使う観測手法・データソース
望遠鏡名、衛星名、解析手法などを箇条書き。

## 関連キーワード
英語・日本語の両方で10〜20語程度。

## 関連度が高い/低いの目安
新着論文が関連するかどうかの判定基準として使われます。
「高い」「中間程度」「低い」の3段階で、境界線がわかるように書いてください。

出力はMarkdown本文のみとし、前置き・後書き・コードフェンスは一切付けないでください。
先頭に `# 研究プロファイル` のような大見出しは付けないでください。

### 過去論文一覧
{papers_block}
{extra_block}
"""


def generate_via_cli(prompt: str) -> str:
    print(f"Claude Code CLI で研究プロファイルを生成中 (model={DEFAULT_MODEL})...")
    return run_claude_text(prompt, model=DEFAULT_MODEL)


def generate_via_api(prompt: str) -> str:
    import anthropic  # api エンジンを選んだときだけ必要

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("--engine api を使うには環境変数 ANTHROPIC_API_KEY が必要です")
    print(f"Anthropic API で研究プロファイルを生成中 (model={API_MODEL}, 従量課金が発生します)...")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=API_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def validate(profile: str) -> None:
    """生成結果が判定基準として使える形になっているかを検査する。

    壊れたプロファイルをそのまま反映すると関連度判定が静かに劣化するため、
    ここで落として人間のレビューを促す。
    """
    if len(profile) < MIN_PROFILE_CHARS:
        sys.exit(f"生成されたプロファイルが短すぎます ({len(profile)}文字)。反映を中止します")
    missing = [h for h in REQUIRED_HEADINGS if h not in profile]
    if missing:
        sys.exit(f"必須の見出しが欠けています: {missing}。反映を中止します")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-name", required=True, help="Semantic Scholar で検索する著者名")
    parser.add_argument(
        "--extra-text-file",
        default=None,
        help="修士論文などから抽出したテキストファイルへのパス(任意)",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "cli", "api"],
        default="auto",
        help="auto(既定): claude CLI があれば cli、なければ api",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "research_profile.md"),
    )
    args = parser.parse_args()

    engine = args.engine
    if engine == "auto":
        engine = "cli" if has_claude() else "api"
        print(f"[情報] エンジンを自動選択しました: {engine}")

    print(f"Semantic Scholar で著者を検索中: {args.author_name}")
    author_id = find_author_id(args.author_name)

    print(f"論文一覧を取得中 (author_id={author_id})")
    papers = fetch_papers(author_id)
    print(f"アブストラクト付き論文が {len(papers)} 件見つかりました")

    extra_text = load_extra_text(args.extra_text_file)
    if not papers and not extra_text:
        sys.exit(
            "アブストラクト付きの論文が見つからず、追加テキストもありません。"
            "--extra-text-file の利用を検討してください"
        )

    prompt = build_prompt(papers, extra_text)
    profile = (generate_via_cli(prompt) if engine == "cli" else generate_via_api(prompt)).strip()
    validate(profile)

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(HEADER + profile + "\n")

    print(f"研究プロファイルを保存しました: {output}")
    print("\n--- プロファイル内容 ---\n")
    print(profile)


if __name__ == "__main__":
    main()
