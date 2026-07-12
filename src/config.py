"""設定。認証情報は環境変数のみ（R: アプリIDのコード直書き禁止）。"""
import os
from pathlib import Path

try:  # .env があれば読む（任意）
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("OSHI_DB_PATH", str(BASE_DIR / "data" / "oshi.db"))
# Supabase等のPostgresを使う場合に設定（未設定ならSQLite）。
# 例: postgresql://user:pass@host:6543/postgres?sslmode=require
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# 公開URL（楽天アプリ登録の「許可されたWebサイト」ドメイン。Refererとして送信）
SITE_URL = os.environ.get("SITE_URL", "")
# Vercel Cron等からの呼び出し保護（VercelはCRON_SECRET設定時に自動でBearer送信）
CRON_SECRET = os.environ.get("CRON_SECRET", "")
# サーバーレス1回の巡回で使うリクエスト数（maxDuration内に収める）
CRAWL_BUDGET_PER_RUN = int(os.environ.get("CRAWL_BUDGET_PER_RUN", "40"))

RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID", "")
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "")  # 2026年より全API必須
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

SITE_NAME = os.environ.get("SITE_NAME", "推しカレンダー")
OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "（運営者名を設定してください）")

# R1: 1リクエスト/秒以下 → 安全側で1.2秒間隔・直列
REQUEST_INTERVAL_SEC = 1.2
MAX_RETRIES = 5           # 429/5xx 指数バックオフ最大5回
BACKOFF_BASE_SEC = 2.0

# R2/R3: キャッシュ保持
PRICE_TTL_HOURS = 24
META_TTL_DAYS = 90
# R4: 巡回周期（最大7日厳守）
CRAWL_PERIOD_DAYS = 7
CRAWL_PERIOD_HOT_DAYS = 3        # 直近60日以内に発売予定がある推し
HOT_WINDOW_DAYS = 60
CRAWL_DAILY_REQUEST_BUDGET = 3000  # 1日1時間枠相当
ALIAS_MAX = 3

# 関連度スコア（§6.2）
SCORE_FIELD_MATCH = 1.0   # author/artistName一致で取得
SCORE_TITLE_MATCH = 0.7
SCORE_CAPTION_MATCH = 0.4
SCORE_THRESHOLD = 0.4     # 未満は非表示

# R9: 成人向け排除。
# 2026-07-12 ライブ確認結果（公開ジャンル一覧ページで確認）:
# - 楽天市場の公開ジャンルツリー（第1・第2階層）に「アダルト」ジャンルは存在しない。
#   成人向け商品は通常ジャンル配下（例: 医薬品>避妊具 等）に分散するため、ID一括除外は不可能。
# - 楽天ブックスの全年齢ジャンル一覧（本/DVD/雑誌/CD/ゲーム/電子書籍）にも成人向けジャンルなし。
#   R18商品は年齢認証付き別ストア（books.rakuten.co.jp/adult/）に分離されている。
# → NGワードを主防御とする。ジャンルIDリストはジャンル再編に備えた予約枠として維持。
#   （最終確認としてBooksGenre/Search APIをappIdで一度実行することを推奨）
EXCLUDED_BOOKS_GENRE_PREFIXES: list[str] = []
EXCLUDED_ICHIBA_GENRE_IDS: set[str] = set()
NG_WORDS = ["アダルト", "成人向け", "成年向け", "成年コミック", "18禁", "R18", "R-18", "官能"]

# 購入可能とみなす在庫状況コード（楽天ブックス系API公式ドキュメントの出力値1〜6）。
# 1:在庫あり 2:通常3〜7日 3:通常3〜9日 4:メーカー取り寄せ 5:予約受付中 6:メーカーに在庫確認
# これ以外のコード（品切れ・販売終了・入手不可等）は表示から除外する。
# 在庫情報が無い媒体（Kobo等、NULL）は安全側で表示する。
PURCHASABLE_AVAILABILITY = {1, 2, 3, 4, 5, 6}

# 検索スパム対策（自前サーバー側。楽天API保護のため）
NEW_SEARCH_PER_IP_PER_MIN = 3

# クレジット表記（R7）: https://webservice.rakuten.co.jp/guide/credit の原文。改変禁止。
CREDIT_SNIPPET = (
    "<!-- Rakuten Web Services Attribution Snippet FROM HERE -->\n"
    '<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>\n'
    "<!-- Rakuten Web Services Attribution Snippet TO HERE -->"
)

# 免責事項（FAQ 900001974343 指定の定型文。●●をサイト名に置換）
def disclaimer() -> str:
    return (
        f"このサイトで掲載されている情報は、{SITE_NAME}の作成者により運営されています。"
        "価格、販売可能情報は、変更される場合があります。"
        "購入時に楽天市場店舗(www.rakuten.co.jp)に表示されている価格が、その商品の販売に適用されます。"
    )
