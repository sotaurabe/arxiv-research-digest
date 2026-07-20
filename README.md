# arXiv 論文リサーチ・翻訳・要約・通知システム

自分の研究分野(初期設定: 恒星フレア / astro-ph.SR, astro-ph.HE)の新着arXiv論文をチェックし、
研究プロファイルと照らして関連度が高いものだけを日本語要約付きで通知します。

## 週次Slack通知モード(推奨・追加費用なし)

ローカルMacだけで完結する構成です。LLM処理はローカルの Claude Code CLI (`claude -p`) が
Pro/Maxプランの利用枠内で行うため、API従量課金は発生しません。

```
毎日 07:00 (launchd: com.sotaurabe.arxiv-fetch)
  └─ scripts/local_fetch_and_push.sh
       arXiv新着を取得し data/candidates.json に蓄積 → push

毎週月曜 08:00 (launchd: com.sotaurabe.arxiv-weekly-digest)
  └─ scripts/weekly_slack_digest.sh
       1. git pull + 直近8日分を追加取得(取りこぼし対策)
       2. scripts/judge_with_claude.py   … claude -p で判定・翻訳・要約
       3. scripts/post_slack_digest.py   … 関連度8以上をSlackに論文ごとに投稿
       4. scripts/finalize_weekly.py     … sent_ids更新・candidatesリセット → push

常駐 (launchd: com.sotaurabe.arxiv-slack-agent)
  └─ scripts/slack_agent.py (Socket Mode)
       投稿された論文のスレッドに返信すると、claude -p が論文の文脈を
       踏まえて回答するAIエージェント。スレッドごとに会話を継続。
```

### セットアップ手順

#### 1. Claude Code CLI

```bash
curl -fsSL https://claude.ai/install.sh | bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
claude   # 初回起動でブラウザが開くのでPro/Maxアカウントでログイン
```

`ANTHROPIC_API_KEY` は**設定しないでください**。設定するとサブスクリプション枠ではなく
API従量課金に切り替わります。

#### 2. Slackアプリの作成

<https://api.slack.com/apps> → **Create New App** → **From scratch** でアプリを作成し、
以下を設定します。

| 設定箇所 | 内容 |
|---|---|
| **Socket Mode** | Enable Socket Mode をON → App-Level Token が発行される(`xapp-`)。スコープは `connections:write` |
| **OAuth & Permissions** → Bot Token Scopes | `chat:write`(投稿)、`reactions:write`(処理中の絵文字)、`channels:history`(スレッド返信の検知) |
| **Event Subscriptions** | Enable Events をON → Subscribe to bot events に `message.channels` を追加 |
| **Install App** | ワークスペースにインストール → Bot User OAuth Token が発行される(`xoxb-`) |

プライベートチャンネルを使う場合は、スコープに `groups:history`、イベントに
`message.groups` も追加してください。

作成後、投稿先チャンネルでボットを招待します(これを忘れると `not_in_channel` エラーになります)。

```
/invite @あなたのアプリ名
```

#### 3. トークンの設定

```bash
cp config/slack.env.example config/slack.env
# エディタで開き、xoxb- / xapp- のトークンとチャンネルIDを記入
```

チャンネルIDはチャンネル名を右クリック → 「リンクをコピー」 → URL末尾の `C0123...` 部分です。
`config/slack.env` は `.gitignore` 済みなのでコミットされません。

#### 4. 常駐エージェントの登録

```bash
cp launchd/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sotaurabe.arxiv-slack-agent.plist
launchctl load ~/Library/LaunchAgents/com.sotaurabe.arxiv-weekly-digest.plist
launchctl list | grep arxiv   # 登録確認
```

#### 5. 動作確認

```bash
# 週次ダイジェストを即時実行(スケジュールを待たずにテスト)
./scripts/weekly_slack_digest.sh && tail -30 weekly_digest.log
```

Slackに投稿されたら、その論文メッセージの**スレッドに返信**してエージェントが応答するか
確認してください。応答しない場合は `launchd_agent_stderr.log` を確認します。

---

## (旧構成) Claude Code ルーティン版 / GitHub Actions 版

以下は代替構成です。ルーティン版はルーティン実行環境のネットワーク制限
(arXiv/Slackへの通信不可、mainへのpush不可)があるため、現在は上記の
ローカル週次モードを推奨しています。

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
