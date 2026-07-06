# ローカル環境セットアップ手順（Windows）と 楽天アプリ登録フォームの入力値

## A. まずローカル環境を動かす（5分）

1. **Python 3.11以降** が未導入なら https://www.python.org/downloads/ からインストール
   （インストーラで「Add python.exe to PATH」に必ずチェック）
2. `oshi-calendar` フォルダの **`setup.bat` をダブルクリック**（仮想環境作成+ライブラリ導入+`.env`生成）
3. **`start.bat` をダブルクリック** → ブラウザで http://localhost:8000 が開けば環境構築完了
   （この時点ではIDが空でも画面は表示されます。検索はID設定後に動きます）

## B. アプリ新規作成フォーム

※フォームの「許可されたWebサイト」は `localhost` を受け付けないことが判明したため、
**先にVercelへデプロイして公開ドメインで登録**します。
→ 手順は `docs/deploy_vercel_supabase.md` を参照してください。

## C. IDを設定して動作確認

1. `.env` をメモ帳で開き、次の4行を入力して保存:
   ```
   RAKUTEN_APP_ID=（アプリID）
   RAKUTEN_ACCESS_KEY=（アクセスキー）
   RAKUTEN_AFFILIATE_ID=（アフィリエイトID）
   OPERATOR_NAME=（サイトに表示する運営者名）
   ```
2. `start.bat` を起動し直し、トップページで推し名を1件検索
   （初回は8媒体を順番に調べるため約10秒。プログレスバーが進めば成功）
3. コマンドラインでの精密確認（Phase 0残タスクのライブ検証）:
   ```
   .venv\Scripts\activate
   python -m src.cli search "推し名"
   ```

## D. 日次ジョブの自動実行（任意・試験運用開始時）

コマンドプロンプトで次を1回実行（毎日3:00に巡回+キャッシュ失効）:
```
schtasks /Create /SC DAILY /ST 03:00 /TN OshiCalendarJobs /TR "C:\（配置先）\oshi-calendar\run_jobs.bat"
```

## 補足

- 「許可されたWebサイト」は後から編集できるため、開発中は `localhost` のみで問題ありません。
  本番公開時にドメインを追記し、アプリケーションURLも本番URLに更新してください。
- 本番は常時稼働できる小型VPS等（規約10条10項の公開アクセス要件を満たす環境）を想定しています。
  デプロイ先が決まりましたら、その環境向けの起動・cron設定もこちらで用意します。
