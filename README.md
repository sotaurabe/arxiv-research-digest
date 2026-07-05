# arXiv 論文リサーチ・翻訳・要約・通知システム(Claude Code ルーティン版)

自分の研究分野(初期設定: 恒星フレア / astro-ph.SR, astro-ph.HE)の新着arXiv論文を毎日チェックし、
研究プロファイルと照らして関連度が高いものだけを日本語要約付きでメール通知します。

**このリポジトリは Claude Code の「ルーティン」機能での実行を前提にしています。**
関連度判定・要約・翻訳は Anthropic API を別途叩くのではなく、ルーティンを実行している
Claude Code エージェント自身が行うため、Proプランの利用枠内で完結し、従量課金は発生しません。

## 仕組み

1. Claude Code ルーティンが毎日1回起動
2. `scripts/fetch_candidates.py` を実行 → arXiv新着を取得し、`data/sent_ids.json` と照合して
   未通知の候補を `data/candidates.json` に書き出す(**APIコールなし・無料**)
3. Claude Code エージェント自身が `config/research_profile.md` と `data/candidates.json` を読み、
   関連度判定・タイトル翻訳・日本語要約を行い、結果を `data/judged.json` に書き出す
   (**ルーティン実行のPro/Maxプラン利用枠内。追加のAPI課金なし**)
4. `scripts/finalize_digest.py` を実行 → 関連度が高いものだけメール送信し、
   `data/sent_ids.json` を更新、一時ファイルを削除する(**APIコールなし・無料**)
5. 変更を commit & push

## なぜこの構成にしたか

素朴に「Pythonスクリプトの中で Anthropic API を呼ぶ」構成にすると、ルーティンをいくら
Proプランで動かしても、スクリプト内の `anthropic.messages.create()` 呼び出しは別途
従量課金の対象になってしまいます。そこで、**LLMとしての判断が必要な部分(関連度判定・翻訳・要約)は
ルーティンを実行しているエージェント自身の "頭" にやらせ、スクリプトは純粋なデータ取得・送信作業
(APIコールを含まない)だけを担当する**、という役割分担にしています。

## data/judged.json のスキーマ

Claude Code エージェントが `data/candidates.json` の各論文を判定した後、以下の形式で
`data/judged.json` に書き出してください。

```json
[
  {
    "id": "2607.01234",
    "title": "原題(英語)",
    "title_ja": "日本語訳タイトル",
    "authors": ["Author One", "Author Two"],
    "url": "https://arxiv.org/abs/2607.01234",
    "relevance_score": 9,
    "reason": "関連度スコアの理由(1文程度)",
    "summary_ja": "200字程度の日本語要約(新規性・研究プロファイルとの関連性を含む)"
  }
]
```

`candidates.json` に含まれる論文は relevance_score が低いものも含めて **全件** judged.json に
含めてください(一度判定した論文を翌日以降また判定し直さないようにするため)。

## セットアップ手順

### 1. GitHub Secrets ではなく、ルーティンの環境変数を設定

このリポジトリは Claude Code ルーティンから実行される前提なので、GitHub Actions の
Secrets ではなく、**ルーティン作成画面の環境変数(Environment Variables)** に以下を設定してください。

| 環境変数名 | 説明 |
|---|---|
| `SMTP_HOST` | 例: `smtp.gmail.com` |
| `SMTP_PORT` | 例: `587` |
| `SMTP_USER` | 送信元メールアドレス |
| `SMTP_PASS` | Gmailの場合はアプリパスワード |
| `EMAIL_TO` | 通知を受け取りたいメールアドレス |
| `EMAIL_FROM` | (任意)差出人アドレス。未設定なら `SMTP_USER` |

`ANTHROPIC_API_KEY` はこの日次フローには不要です(ルーティン自体がClaudeのセッションのため)。
`scripts/build_profile.py` を手元で実行してプロファイルを更新したい場合のみ、
その時だけ環境変数として設定してください。

### 2. ルーティンを作成

`claude.ai/code/routines`、または CLI で `/schedule` から作成し、以下を設定します。

- リポジトリ: このリポジトリ
- 環境変数: 上記の表の内容
- トリガー: Schedule → 毎日1回
- プロンプト: 別途渡している「ルーティン用システムプロンプト」を貼り付け

### 3. 動作確認

ルーティンの手動実行(Run now 相当の操作)でメールが届くか確認してください。

## ファイル構成

```
.
├── .github/workflows/
│   └── daily-digest.yml       # GitHub Actions版(Anthropic API課金を許容する場合の代替手段)
├── scripts/
│   ├── build_profile.py       # 研究プロファイル生成(手動・任意。Anthropic APIを使用)
│   ├── daily_digest.py        # GitHub Actions版のメインパイプライン(上記workflowから実行)
│   ├── fetch_candidates.py    # 新着取得+重複排除(APIコールなし)
│   └── finalize_digest.py     # メール送信+送信済み記録更新(APIコールなし)
├── config/
│   ├── research_profile.md    # 研究プロファイル(判定基準)
│   └── thesis_summary_ja.txt  # 修士論文からの参考メモ
├── data/
│   └── sent_ids.json          # 通知済みarXiv IDの記録(重複排除用)
└── requirements.txt
```

`.github/workflows/daily-digest.yml` は GitHub Actions + Anthropic API 課金を許容する場合の
代替手段として残していますが、Claude Code ルーティンで運用する場合は使いません(重複実行を
避けるため、どちらか一方だけを有効にしてください)。
