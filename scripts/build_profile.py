"""
研究プロファイル生成スクリプト

Semantic Scholar から著者の過去論文(タイトル・アブストラクト)を取得し、
Claude にそれらを読ませて「研究プロファイル(テーマ・キーワード・問題設定)」を
自然文で生成させる。生成結果は config/research_profile.md に保存され、
daily_digest.py が毎日の関連度判定の "ものさし" として利用する。

使い方:
    export ANTHROPIC_API_KEY=xxxx
    python scripts/build_profile.py --author-name "Sota Urabe"

論文が増えたら再実行すればプロファイルを更新できる。
"""

import argparse
import json
import os
import sys
import time

import requests
import anthropic

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/author/search"
SEMANTIC_SCHOLAR_PAPERS_URL = "https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
MODEL = "claude-sonnet-4-6"


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
    """著者の論文一覧(タイトル・アブストラクト・年)を取得する。"""
    resp = requests.get(
        SEMANTIC_SCHOLAR_PAPERS_URL.format(author_id=author_id),
        params={"fields": "title,abstract,year,externalIds"},
        timeout=30,
    )
    resp.raise_for_status()
    papers = resp.json().get("data", [])
    # アブストラクトがある論文のみ使う
    return [p for p in papers if p.get("abstract")]


def load_extra_text(path: str | None) -> str:
    """修士論文などの追加テキストファイルがあれば読み込む(任意)。"""
    if not path:
        return ""
    if not os.path.exists(path):
        print(f"[警告] 追加テキストファイルが見つかりません: {path}")
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_profile_text(papers: list[dict], extra_text: str, client: anthropic.Anthropic) -> str:
    papers_block = "\n\n".join(
        f"タイトル: {p['title']}\n年: {p.get('year', '不明')}\nアブストラクト: {p['abstract']}"
        for p in papers
    )

    extra_block = f"\n\n### 追加参考資料(修士論文など)からの抜粋\n{extra_text[:8000]}" if extra_text else ""

    prompt = f"""あなたは研究者の興味・専門性を分析するアシスタントです。
以下は、ある研究者の過去の発表論文のタイトルとアブストラクトです。
これらを読んで、この研究者の「研究プロファイル」を日本語で作成してください。

プロファイルには以下を含めてください:
1. 主要な研究テーマ(2〜4個程度)
2. よく使われる観測手法・データソース(望遠鏡名、衛星名、解析手法など)
3. 関連の深いキーワード(英語・日本語の両方、10〜20語程度)
4. このプロファイルを「新着論文が関連するかどうかの判定基準」として使う旨を意識し、
   何が「関連度が高い」で何が「関連度が低い」かの境界線がわかるように書いてください。

出力はプロファイル本文のみとし、前置きや後書きは不要です。

### 過去論文一覧
{papers_block}
{extra_block}
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--author-name", required=True, help="Semantic Scholar で検索する著者名")
    parser.add_argument(
        "--extra-text-file",
        default=None,
        help="修士論文などから抽出したテキストファイルへのパス(任意)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "research_profile.md"),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("環境変数 ANTHROPIC_API_KEY を設定してください")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"Semantic Scholar で著者を検索中: {args.author_name}")
    author_id = find_author_id(args.author_name)

    print(f"論文一覧を取得中 (author_id={author_id})")
    papers = fetch_papers(author_id)
    print(f"アブストラクト付き論文が {len(papers)} 件見つかりました")

    if not papers:
        sys.exit("アブストラクト付きの論文が見つかりませんでした。--extra-text-file の利用を検討してください")

    extra_text = load_extra_text(args.extra_text_file)

    print("Claude で研究プロファイルを生成中...")
    profile = build_profile_text(papers, extra_text, client)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(profile)

    print(f"研究プロファイルを保存しました: {args.output}")
    print("\n--- プロファイル内容 ---\n")
    print(profile)


if __name__ == "__main__":
    main()
