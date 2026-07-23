"""
毎日実行するメインパイプライン

1. arXiv API から指定カテゴリの新着論文を取得
2. 既に通知済みの ID を除外(重複排除)
3. 研究プロファイルと突き合わせて Claude に関連度判定させる
4. 関連度が高いものだけ、日本語要約・タイトル翻訳を生成
5. メールで送信
6. 送信済み ID を記録して更新

GitHub Actions から日次実行される想定。
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import requests
import anthropic

# ==== 設定項目(必要に応じて書き換えてください) ====
ARXIV_CATEGORIES = ["astro-ph.SR", "astro-ph.HE"]
LOOKBACK_DAYS = 1  # 何日分の新着を見るか(毎日実行なら1でOK。実行間隔を空けるなら増やす)
# 10点満点中、これ以上のスコアのみ通知(本数より精度重視)。
# 変更は環境変数 RELEVANCE_THRESHOLD で行う(GitHub の Actions variables から設定可能)。
RELEVANCE_THRESHOLD = int(os.environ.get("RELEVANCE_THRESHOLD", "8"))
MAX_CANDIDATES_PER_RUN = 150  # 1回の判定に投げる論文数の上限(コスト対策)
MODEL = "claude-sonnet-4-6"
# ===================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(BASE_DIR, "config", "research_profile.md")
SENT_IDS_PATH = os.path.join(BASE_DIR, "data", "sent_ids.json")

ARXIV_API_URL = "http://export.arxiv.org/api/query"


def fetch_recent_papers() -> list[dict]:
    """arXiv API から指定カテゴリの新着論文を取得する。"""
    # 区切りは半角スペースにする。"+OR+" と書くと requests が "+" を %2B に
    # エンコードし、arXiv 側でクエリが壊れて常に0件になる
    category_query = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    params = {
        "search_query": category_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": MAX_CANDIDATES_PER_RUN,
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


def load_sent_ids() -> set:
    if not os.path.exists(SENT_IDS_PATH):
        return set()
    with open(SENT_IDS_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_sent_ids(ids: set):
    os.makedirs(os.path.dirname(SENT_IDS_PATH), exist_ok=True)
    with open(SENT_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def load_profile() -> str:
    if not os.path.exists(PROFILE_PATH):
        sys.exit(
            f"研究プロファイルが見つかりません: {PROFILE_PATH}\n"
            "先に scripts/build_profile.py を実行して生成してください"
        )
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return f.read()


def judge_and_summarize(papers: list[dict], profile: str, client: anthropic.Anthropic) -> list[dict]:
    """関連度判定と要約・翻訳をまとめて1回の呼び出しで行う。"""
    if not papers:
        return []

    papers_block = "\n\n".join(
        f"[{i}] id: {p['id']}\nタイトル: {p['title']}\nアブストラクト: {p['abstract']}"
        for i, p in enumerate(papers)
    )

    prompt = f"""あなたは研究者向けの論文フィルタリング・要約アシスタントです。
以下の「研究プロファイル」を持つ研究者にとって、各論文がどれだけ関連が深いかを判定してください。

### 研究プロファイル
{profile}

### 判定対象の論文一覧
{papers_block}

各論文について、次の JSON 配列形式で出力してください。前置きや説明文は一切不要で、JSON配列のみを出力してください。

[
  {{
    "index": 論文番号(int),
    "relevance_score": 関連度スコア(1〜10の整数。研究プロファイルとの関連の深さ),
    "reason": "関連度スコアをつけた理由(日本語、1文程度)",
    "title_ja": "タイトルの日本語訳",
    "summary_ja": "200字程度の日本語要約(何が新しいか・研究プロファイルとの関連性を含む)"
  }}
]

relevance_score が低い論文についても title_ja と summary_ja は簡潔でよいので必ず埋めてください。
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(block.text for block in message.content if block.type == "text")

    # モデルがコードフェンスを付けた場合に備えて除去
    cleaned = re.sub(r"^```json|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    try:
        results = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print("[エラー] Claude の応答を JSON として解析できませんでした:", e)
        print(raw_text[:2000])
        return []

    enriched = []
    for r in results:
        idx = r.get("index")
        if idx is None or not (0 <= idx < len(papers)):
            continue
        paper = dict(papers[idx])
        paper.update(
            {
                "relevance_score": r.get("relevance_score", 0),
                "reason": r.get("reason", ""),
                "title_ja": r.get("title_ja", paper["title"]),
                "summary_ja": r.get("summary_ja", ""),
            }
        )
        enriched.append(paper)
    return enriched


def build_email_body(relevant_papers: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"本日の関連論文ダイジェスト ({today})", f"該当件数: {len(relevant_papers)}件", ""]
    for p in sorted(relevant_papers, key=lambda x: -x["relevance_score"]):
        lines.append("=" * 60)
        lines.append(f"■ {p['title_ja']}")
        lines.append(f"  原題: {p['title']}")
        lines.append(f"  著者: {', '.join(p['authors'][:6])}")
        lines.append(f"  関連度スコア: {p['relevance_score']}/10 ({p['reason']})")
        lines.append(f"  URL: {p['url']}")
        lines.append("")
        lines.append(f"  {p['summary_ja']}")
        lines.append("")
    return "\n".join(lines)


def send_email(subject: str, body: str):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    email_to = os.environ["EMAIL_TO"]
    email_from = os.environ.get("EMAIL_FROM", smtp_user)

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(email_from, [email_to], msg.as_string())


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("環境変数 ANTHROPIC_API_KEY を設定してください")
    client = anthropic.Anthropic(api_key=api_key)

    profile = load_profile()
    sent_ids = load_sent_ids()

    print("arXiv から新着論文を取得中...")
    papers = fetch_recent_papers()
    print(f"新着 {len(papers)} 件取得")

    candidates = [p for p in papers if p["id"] not in sent_ids]
    print(f"未通知の候補: {len(candidates)} 件")

    if not candidates:
        print("新規候補がないため終了します")
        return

    print("Claude で関連度判定・要約生成中...")
    judged = judge_and_summarize(candidates, profile, client)

    relevant = [p for p in judged if p["relevance_score"] >= RELEVANCE_THRESHOLD]
    print(f"関連度 {RELEVANCE_THRESHOLD} 以上: {len(relevant)} 件")

    if relevant:
        body = build_email_body(relevant)
        subject = f"[論文ダイジェスト] 関連論文 {len(relevant)}件 ({datetime.now().strftime('%Y-%m-%d')})"
        send_email(subject, body)
        print("メールを送信しました")
    else:
        print("本日は関連度の高い論文がありませんでした(メール送信はスキップ)")

    # 判定した全候補(関連度に関わらず)を送信済みとして記録し、重複判定を避ける
    sent_ids.update(p["id"] for p in judged)
    save_sent_ids(sent_ids)
    print("送信済みIDを更新しました")


if __name__ == "__main__":
    main()
