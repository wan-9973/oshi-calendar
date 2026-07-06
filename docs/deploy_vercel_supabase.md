# Vercel + Supabase デプロイ手順

## 全体の流れ（鶏と卵の解消）

楽天のフォームが `localhost` を受け付けないため、**先にVercelへデプロイして公開URLを確定**させ、
そのドメインで楽天アプリを登録し、取得したIDを後からVercelの環境変数に追加します。

```
①Supabase作成 → ②Vercelデプロイ(ID未設定でOK) → ③楽天アプリ登録 → ④ID設定+再デプロイ → ⑤動作確認
```

## ① Supabase（DB）

1. https://supabase.com で New project（無料プラン可。リージョンは Tokyo 推奨）
2. Settings → Database → Connection string → **Transaction pooler**（ポート6543）のURIをコピー
3. 末尾に `?sslmode=require` を付け、`[YOUR-PASSWORD]` を実パスワードに置換
   例: `postgresql://postgres.xxxx:パスワード@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres?sslmode=require`

※テーブルは初回起動時に自動作成されます（手動SQLは不要）。

## ② Vercel（アプリ）

1. このフォルダをGitHubリポジトリにpush（**`.env`は絶対にコミットしない**。`data/`も不要）
2. https://vercel.com → Add New → Project → リポジトリをImport（Framework Preset: Other のまま）
3. Environment Variables に以下を設定して Deploy:

| 変数 | 値 |
|---|---|
| `DATABASE_URL` | ①でコピーした接続文字列 |
| `SITE_NAME` | 推しカレンダー |
| `OPERATOR_NAME` | サイトに表示する運営者名 |
| `CRON_SECRET` | ランダムな長い文字列（例: `openssl rand -hex 32` の出力） |

4. デプロイ完了後のURL（例: `https://oshi-calendar.vercel.app`）を控える。
   この時点でトップページは表示されます（検索は③④の後に動きます）。

## ③ 楽天アプリ登録フォームの入力値

| フォーム項目 | 入力値 |
|---|---|
| アプリケーション名 | `推しカレンダー` |
| アプリケーションURL | `https://oshi-calendar.vercel.app`（②の実URL） |
| アプリケーションタイプ | `Webアプリケーション` |
| 許可されたWebサイト | `oshi-calendar.vercel.app`（②の実ドメイン。httpsなしのドメインのみ） |
| アプリケーションの説明 | 現在入力されている文面でOK |

## ④ IDをVercelに設定

1. Vercel → プロジェクト → Settings → Environment Variables に追加:
   `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID` /
   `SITE_URL`（=②の実URL。APIリクエストのRefererとして送信）
2. Deployments → 最新デプロイの「…」→ Redeploy（環境変数を反映）

## ⑤ 動作確認（ライブ検証）

1. トップページで推し名を1件検索（約10〜15秒。プログレスバーが進んで推しページが開けば成功）
2. 実在推し3件（作家・アーティスト・声優など）で検索し、ノイズ・関連度を確認
   → 結果に違和感があれば共有してください。閾値(0.4)や除外ジャンルを調整します
3. cron動作確認（手動実行）:
   `curl -H "Authorization: Bearer （CRON_SECRET）" https://（実URL）/api/cron/crawl`

## サーバーレス構成での動作の違い（重要）

- **検索は同期実行**（8API×1.2秒≒10秒。関数のmaxDuration=60秒以内）。画面は疑似プログレス表示。
- **R1のレート制御はDB行ロックで全インスタンス横断の直列化**（`rate_state`テーブル）。
- **巡回はVercel Cronで毎日1回**（JST 3:00、1回40リクエスト≒推し5件）。
  - 容量目安: 7日周期で**約35推し**。超える場合は `.github/workflows/crawl.yml.example` を
    有効化してGitHub Actionsから10分間隔で増枠（無料）するか、Vercel Proのcronを利用。
  - キャッシュ失効はJST 2:30に毎日実行。
- Supabase無料プランは長期間アクセスがないとプロジェクトが一時停止される場合がありますが、
  日次cronが動いていれば実質問題になりません（停止された場合はダッシュボードからRestore）。

## 規約上の注意（変わらず有効）

- 公開アプリになるため、フッターの運営者表記（`OPERATOR_NAME`）を必ず実名義に設定
- DB（Supabase）は非公開のまま維持（生データ再配布禁止・規約10条9項）
- プレスリリースは楽天の事前書面許可が必要（規約19条）
