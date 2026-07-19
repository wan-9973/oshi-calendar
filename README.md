# 推しカレンダー（推し活サプライチェーン・マネージャー）

「推し」の名前を登録するだけで、楽天ブックス・楽天Kobo・楽天市場を横断検索し、
新刊・新譜・発売予定・関連商品を1つの供給カレンダーとして表示する無料公開Webアプリ。
全商品リンクは楽天アフィリエイトリンクです。

## デプロイ形態

- **本番（推奨）**: Vercel + Supabase → `docs/deploy_vercel_supabase.md`
- **ローカル開発（Windows）**: `setup.bat` / `start.bat` → `docs/local_setup_windows.md`

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env   # 3つの環境変数とOPERATOR_NAMEを設定（コード直書き禁止）
```

必要な認証情報（§3）:
1. `RAKUTEN_APP_ID` … https://webservice.rakuten.co.jp/app/create
2. `RAKUTEN_ACCESS_KEY` … https://webservice.rakuten.co.jp/app/list （**2026年より全API必須**）
3. `RAKUTEN_AFFILIATE_ID` … https://webservice.rakuten.co.jp/app/account_affiliate_id

## 起動

```bash
# CLI検証（Phase 1完了条件）
python -m src.cli search "推し名" --alias "別名"

# Webサーバー
uvicorn src.web.app:app --host 0.0.0.0 --port 8000
```

## 運用ジョブ（crontab.example 参照）

- `python -m src.crawler` … 日次巡回。全推しを最大7日周期で更新（R4）。直近60日に発売予定がある推しは3日周期。

Vercel運用では `GET /api/health` が、直近のcrawl/retention成功時刻、実行結果、
期限を過ぎた巡回キュー件数を返します。商品カードは推し単位のローテーションで更新されるため、
カード上の取得日時ではなくこのAPIを日次監視の一次判定に使用してください。

アプリ本体の生存確認は `/api/health` と分け、毎朝の監視で本番トップページにもHTTP GETを行い、
`https://oshi-calendar-ten.vercel.app/` が **HTTP 200** を返すことを確認してください。
リダイレクトや5xxを成功扱いにせず、`/api/health` のJSON判定とトップページの200判定を
それぞれ独立したチェックとして通知する運用を推奨します（Cron設定・レスポンス構造の変更は不要です）。
- `python -m src.retention` … 価格キャッシュ24時間失効（R2）、メタデータ90日再取得（R3）、90日未使用推しの削除。

## 規約適合の実装ポイント

- R1: 全APIリクエストはプロセス内で直列化し1.2秒間隔（`rakuten_client.RateLimiter`）。ユーザー起因検索も同一リミッタを通る。**uvicornはワーカー1プロセスで運用すること**（複数プロセスにするとレート制御が分裂します）。
- R5/R6: 課金機能なし。商品カードのリンクは`affiliateUrl`（楽天ドメイン）のみ。外部リンクなし。
- R7: フッターのクレジットは公式スニペット原文（改変禁止）。
- R8: ログインなし。マイ推しリストはlocalStorageのみで、サーバーに個人データを保存しない。
- R9: NGワード+除外ジャンルIDフィルタ（`config.py`。ジャンルIDはライブ確認後に設定）。
- R10: **プレスリリースを打つ場合は楽天の事前書面許可が必要（規約19条）。無断発表禁止。**
- 生データの再配布・DB公開はしない（規約10条9項）。`data/oshi.db`は非公開に保つこと。

## 構成

```
src/
├─ rakuten_client.py    # APIクライアント（レート制御・リトライ・部分成功）
├─ search_service.py    # 8API直列横断検索+正規化+保存
├─ dedupe.py            # 名寄せ・関連度スコア・成人向け排除
├─ calendar_service.py  # salesDateパーサとカレンダー生成
├─ crawler.py           # 定期巡回（新着検知・周期管理）
├─ retention.py         # 24h/90dキャッシュ失効
└─ web/                 # FastAPI + テンプレート + localStorage個人化
```

## テスト

```bash
python -m pytest tests/ -q   # 31件（名寄せ/関連度/除外/レート制御/巡回/失効/画面要素）
```
