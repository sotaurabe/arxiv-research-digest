"""
Claude Code(エージェント自身)が作成した data/judged.json を元に、
関連度の高い論文だけをメール送信し、送信済みIDを更新するスクリプト。

このスクリプトも Anthropic API を一切呼び出しません(=課金が発生しません)。

入力: data/judged.json
  [
    {
      "id": "2607.xxxxx",
      "title": "...",                # 原題
      "title_ja": "...",             # 日本語訳タイトル
      "authors": ["...", ...],
      "url": "https://arxiv.org/abs/...",
      "relevance_score": 9,          # 1-10
      "reason": "...",               # 判定理由(短文)
      "summary_ja": "..."            # 日本語要約
    },
    ...
  ]

data/judged.json に含まれる id は「判定済み」として全て sent_ids.json に追記されます
(relevance_score が低いものも含む。二度と判定し直さないようにするため)。
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 変更は環境変数 RELEVANCE_THRESHOLD で行う(GitHub の Actions variables から設定可能)
RELEVANCE_THRESHOLD = int(os.environ.get("RELEVANCE_THRESHOLD", "8"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT_IDS_PATH = os.path.join(BASE_DIR, "data", "sent_ids.json")
JUDGED_PATH = os.path.join(BASE_DIR, "data", "judged.json")


def load_sent_ids() -> set:
    if not os.path.exists(SENT_IDS_PATH):
        return set()
    with open(SENT_IDS_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_sent_ids(ids: set):
    os.makedirs(os.path.dirname(SENT_IDS_PATH), exist_ok=True)
    with open(SENT_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


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
    if not os.path.exists(JUDGED_PATH):
        sys.exit(f"{JUDGED_PATH} が見つかりません。先に判定結果を書き出してください")

    with open(JUDGED_PATH, encoding="utf-8") as f:
        judged = json.load(f)

    relevant = [p for p in judged if p.get("relevance_score", 0) >= RELEVANCE_THRESHOLD]

    if relevant:
        body = build_email_body(relevant)
        subject = f"[論文ダイジェスト] 関連論文 {len(relevant)}件 ({datetime.now().strftime('%Y-%m-%d')})"
        send_email(subject, body)
        print(f"メールを送信しました({len(relevant)}件)")
    else:
        print("関連度の高い論文がなかったため、メール送信はスキップしました")

    sent_ids = load_sent_ids()
    sent_ids.update(p["id"] for p in judged)
    save_sent_ids(sent_ids)
    print(f"送信済みIDを更新しました(累計 {len(sent_ids)} 件)")

    # 一時ファイルの後始末
    for tmp in ["candidates.json", "judged.json"]:
        path = os.path.join(BASE_DIR, "data", tmp)
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    main()
