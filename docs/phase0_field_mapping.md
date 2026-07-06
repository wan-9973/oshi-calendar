# Phase 0 検証レポート: APIフィールドマッピング表

調査日: 2026-07-06 / 調査方法: 各APIの公式ドキュメントページを取得し原文を確認

## 1. エンドポイント一覧（確認済み・原文どおり）

| API | リクエストURL | version |
|---|---|---|
| Books書籍検索 | `https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404` | 2017-04-04 |
| BooksCD検索 | `https://openapi.rakuten.co.jp/services/api/BooksCD/Search/20170404` | 2017-04-04 |
| BooksDVD/Blu-ray検索 | `https://openapi.rakuten.co.jp/services/api/BooksDVD/Search/20170404` | 2017-04-04 |
| Books雑誌検索 | `https://openapi.rakuten.co.jp/services/api/BooksMagazine/Search/20170404` | 2017-04-04 |
| Booksゲーム検索 | `https://openapi.rakuten.co.jp/services/api/BooksGame/Search/20170404` | 2017-04-04 |
| Books総合検索 | `https://openapi.rakuten.co.jp/services/api/BooksTotal/Search/20170404` | 2017-04-04 |
| Kobo電子書籍検索 | `https://openapi.rakuten.co.jp/services/api/Kobo/EbookSearch/20170426` | 2017-04-26 |
| 市場商品検索 | `https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401` | **2026-04-01** |

## 2. 手順書との差分（重要）

1. **accessKeyが全8APIで必須化**（ドキュメント上「必須 / Required along with app ID」と明記。ヘッダーまたはクエリパラメータで送付可）。
   → 環境変数 `RAKUTEN_ACCESS_KEY` を追加。取得場所: https://webservice.rakuten.co.jp/app/list
2. **CD/DVDのアーティスト指定パラメータは `artist` ではなく `artistName`**（手順書§6.1の `artist=推し名` は現行仕様と不一致）。
3. **DVD/雑誌/ゲーム検索に `keyword` パラメータは存在しない**。固有パラメータは title / artistName(CD,DVD) / label / jan / booksGenreId。
   → DVDは `artistName`（高信頼）、雑誌・ゲームは `title` で検索し、タイトル横断の補完は BooksTotal の `keyword` で行う設計に変更。
4. **市場商品検索(2026-04-01版)のパスは `/ichibams/api/`**（従来の `/services/api/` から変更）。sortに `-updateTimestamp` あり（手順書の想定どおり利用可能）。

## 3. 検索パラメータマッピング（推し名検索時）

| # | API | パラメータ | 信頼度trust | 備考 |
|---|---|---|---|---|
| 1 | BooksBook | `author=推し名` | 1.0 | sort=-releaseDate, outOfStockFlag=1 |
| 2 | BooksCD | `artistName=推し名` | 1.0 | 同上 |
| 3 | BooksDVD | `artistName=推し名` | 1.0 | 同上 |
| 4 | BooksMagazine | `title=推し名` | 要再検証 | keywordなし |
| 5 | BooksGame | `title=推し名` | 要再検証 | keywordなし |
| 6 | Kobo | `author=推し名` | 1.0 | title/author/publisherName/keyword/koboGenreId対応 |
| 7 | Ichiba | `keyword=推し名` | 要再検証 | sort=-updateTimestamp |
| 8 | BooksTotal | `keyword=推し名` | 要再検証 | DVD/雑誌/ゲームのタイトル未ヒット補完 |

基本8リクエスト/推し（別名3件併用時は最大32）。§7.2の周期計算は32リクエスト基準で再計算済み（1日3,000リクエスト枠・7日周期で約650推し）。

## 4. 共通仕様（確認済み）

- `formatVersion=2` 全API対応（items配列が平坦化される）
- `affiliateId` 指定時、出力に `affiliateUrl` が含まれる（PC/mobile両対応https）
- エラー: 400 wrong_parameter / 404 not_found / 429 too_many_requests / 500 / 503 maintenance
- Books系の `title, author(artistName), label, sort` 等の値は個別にUTF-8 URLエンコード必須

## 5. 発売日（salesDate）形式（確認済み・Books系/Kobo共通）

表示例: 「YYYY年」「YYYY年MM月」「YYYY年MM月DD日」。発売日未確定の場合「上旬/中旬/下旬」「頃」「以降」等が付加される。

→ パーサー方針: 正規表現で年/月/日を抽出。日欠落時は 上旬=5日・中旬=15日・下旬=25日・指定なし=月末 で近似ソート値を生成し、表示は原文のまま保持（精度フラグ year/month/day を併記）。市場商品には発売日フィールドがないためカレンダー対象外（新着欄のみ）。

## 6. クレジット表記（R7・原文スニペット確認済み）

テキスト版を改変せずフッターに設置:

```html
<!-- Rakuten Web Services Attribution Snippet FROM HERE -->
<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>
<!-- Rakuten Web Services Attribution Snippet TO HERE -->
```

## 7. 未完了項目（要・認証情報）

- 実在推し名3件でのライブ検索テストと関連度スコア閾値(0.4)の妥当性確認は、`RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` 設定後に `python -m src.cli search "推し名"` で実施する。
- 成人向け除外ジャンルID（Books/市場）はライブ環境でBooksGenre/Search・市場ジャンルAPIから確定させる。それまでconfigのNGワードフィルタ+ジャンルIDプレースホルダで安全側に倒す。
