# arXiv 論文リサーチ・翻訳・要約・通知システム

自分の研究分野(初期設定: 恒星フレア / astro-ph.SR, astro-ph.HE)の新着arXiv論文を毎日チェックし、
研究プロファイルと照らして関連度が高いものだけを日本語要約付きでメール通知します。

## 仕組み

1. GitHub Actions が毎日定時に起動(JST 8:00 / `workflow_dispatch` で手動実行も可)
2. arXiv API から指定カテゴリの新着論文を取得
3. `data/sent_ids.json` と照合し、通知済みの論文を除外
4. `config/research_profile.md` の内容をものさしに、Claude が関連度を判定(10点満点、閾値以上のみ通知)
5. 関連度が高い論文だけ日本語要約・タイトル翻訳を生成
6. メールで送信し、送信済みIDを更新してリポジトリにコミット

## セットアップ手順

### 1. リポジトリを作成してこのフォルダの中身をpush

```bash
git init
git add .
git commit -m "init: arxiv research digest"
git remote add origin <あなたのGitHubリポジトリURL>
git push -u origin main
```

### 2. GitHub Secrets を設定

リポジトリの Settings → Secrets and variables → Actions で以下を登録してください。

| Secret名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic APIキー |
| `SMTP_HOST` | 例: `smtp.gmail.com` |
| `SMTP_PORT` | 例: `587` |
| `SMTP_USER` | 送信元メールアドレス |
| `SMTP_PASS` | Gmailの場合はアプリパスワード(通常のパスワードではなくアプリパスワードを発行してください) |
| `EMAIL_TO` | 通知を受け取りたいメールアドレス |
| `EMAIL_FROM` | (任意)差出人アドレス。未設定なら `SMTP_USER` が使われます |

Gmailを使う場合、Googleアカウントの「アプリパスワード」を発行して `SMTP_PASS` に設定してください
(2段階認証の有効化が前提です)。

### 3. 研究プロファイルを生成・更新する(任意・推奨)

`config/research_profile.md` には初期の下書きが入っていますが、
実際の過去論文リストから自動生成し直すには、ローカルで以下を実行してください。

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=xxxx
python scripts/build_profile.py --author-name "Sota Urabe"
```

修士論文などのテキストも加味したい場合は、あらかじめPDFからテキストを抽出したファイルを用意し、
`--extra-text-file path/to/thesis.txt` を追加してください。

今回は修士論文(卜部聡太, 2023年度「Hαフレア」)の内容を実際に読み込み、
`config/thesis_summary_ja.txt` としてメモをまとめた上で `config/research_profile.md` に反映済みです。
論文のPDFはスキャン起因ではなく通常のLaTeX組版ですが、日本語フォントのCIDマッピングの都合で
`pdftotext`/`pypdf` によるテキスト抽出では文字化けするため、該当ページを画像化して内容を確認しました。
今後さらに論文が増えた場合は、同様にページを画像化して内容を読み取るか、
`build_profile.py --extra-text-file config/thesis_summary_ja.txt` の形で再生成に使ってください。

生成された `config/research_profile.md` をコミット・pushすれば、翌日以降の判定に反映されます。
論文が増えたら再実行して更新するのがおすすめです。

### 4. 動作確認

Actions タブから `Daily arXiv Digest` ワークフローを選び、`Run workflow` で手動実行して
メールが届くか確認してください。

## カスタマイズ

`scripts/daily_digest.py` の冒頭にある設定項目で調整できます。

- `ARXIV_CATEGORIES`: 対象とするarXivカテゴリ(例: `["astro-ph.SR", "astro-ph.HE"]`)
- `RELEVANCE_THRESHOLD`: 通知する関連度スコアの閾値(10点満点、デフォルト8)
- `LOOKBACK_DAYS`: 何日分の新着を見るか
- `.github/workflows/daily-digest.yml` の `cron` で実行時刻を変更可能

## ファイル構成

```
.
├── .github/workflows/daily-digest.yml   # 毎日の自動実行
├── scripts/
│   ├── build_profile.py                 # 研究プロファイル生成(初回・更新時に手動実行)
│   └── daily_digest.py                  # 毎日実行されるメインパイプライン
├── config/
│   └── research_profile.md              # 研究プロファイル(判定基準)
├── data/
│   └── sent_ids.json                    # 通知済みarXiv IDの記録(重複排除用)
└── requirements.txt
```
