"""
Morning brief pipeline entry point.

Usage:
    python src/main.py                # build report, save to data/ (no email)
    python src/main.py --send-email   # also send via Gmail
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Allow running both as `python src/main.py` and via run_local.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data.price import fetch_all_prices, CONFIG_PATH
from data.ib_opinion import fetch_ib_opinions
from data.news import fetch_all_news
from analysis.technical import compute_technical_scores
from analysis.sentiment import score_news, load_keywords
from analysis.fundamental import compute_fundamental_scores
from scoring import build_composite, rank_picks, load_scoring_config
from report.builder import build_report
from report.email_sender import send_report_email

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def run(send_email: bool = False, news_max_tickers: int = 50, config_path: str | Path = CONFIG_PATH) -> bool:
    DATA_DIR.mkdir(exist_ok=True)
    stamp = datetime.today().strftime("%Y%m%d")

    scoring_config = load_scoring_config()
    keywords = load_keywords()

    logger.info("=== 1/6 Fetching prices ===")
    prices = fetch_all_prices(config_path)
    if prices.empty:
        logger.error("No price data collected. Aborting.")
        return False
    prices.to_csv(DATA_DIR / f"prices_{stamp}.csv", index=False)

    logger.info("=== 2/6 Technical analysis ===")
    tech_df = compute_technical_scores(prices, scoring_config)

    logger.info("=== 3/6 Fetching IB opinions (yfinance-compatible tickers) ===")
    yf_mask = (prices["country"] != "KR") | prices["ticker"].str.contains(r"\.K[SQ]", regex=True)
    opinion_df = fetch_ib_opinions(prices[yf_mask])

    logger.info("=== 4/6 Fetching news & sentiment ===")
    news_df = fetch_all_news(prices, max_per_ticker=5, max_tickers=news_max_tickers)
    if not news_df.empty:
        news_df.to_csv(DATA_DIR / f"news_{stamp}.csv", index=False)
    sentiment_df = score_news(news_df, keywords)

    logger.info("=== 5/6 Fundamental & composite scoring ===")
    fund_df = compute_fundamental_scores(opinion_df, sentiment_df, tech_df, scoring_config)
    composite_df = build_composite(tech_df, fund_df, scoring_config)
    composite_df.to_csv(DATA_DIR / f"scores_{stamp}.csv", index=False)
    picks = rank_picks(composite_df, scoring_config)

    logger.info("=== 6/6 Building report ===")
    html = build_report(composite_df, picks, scoring_config)
    report_path = DATA_DIR / f"report_{stamp}.html"
    report_path.write_text(html, encoding="utf-8")
    logger.info("Report saved: %s", report_path)

    if send_email:
        subject = f"[증시 모닝 브리프] {datetime.today().strftime('%Y-%m-%d')}"
        return send_report_email(subject, html)
    return True


def main():
    parser = argparse.ArgumentParser(description="Stock morning brief pipeline")
    parser.add_argument("--send-email", action="store_true", help="send report via Gmail SMTP")
    parser.add_argument("--news-max-tickers", type=int, default=50, help="max tickers for news collection")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="path to universe.yaml")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ok = run(send_email=args.send_email, news_max_tickers=args.news_max_tickers, config_path=args.config)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
