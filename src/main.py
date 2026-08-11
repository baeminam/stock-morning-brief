"""
Morning brief pipeline entry point.

Usage:
    python src/main.py                # build report, save to data/ (no email)
    python src/main.py --send-email   # also send via Gmail
"""

import argparse
import logging
import os
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
from report.ai_commentary import generate_commentary, translate_jp_names, is_available as ai_available, MODEL_LABEL
from report.builder import build_report, build_text_report
from report.email_sender import send_report_email
from report.pdf_report import build_pdf

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_dotenv():
    """Load KEY=VALUE lines from project .env into os.environ (local use only)."""
    env_path = DATA_DIR.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _describe_universe(prices, config_path) -> list[str]:
    """Build human-readable notes explaining each market's universe size."""
    from data.price import load_config

    config = load_config(config_path)
    counts = prices.groupby("country")["ticker"].nunique().to_dict() if not prices.empty else {}
    notes = []

    if counts.get("KR"):
        kr_cfg = config.get("kr", {})
        kr_tickers = prices[prices["country"] == "KR"]["ticker"]
        if kr_tickers.str.contains(r"\.K[SQ]", regex=True).any():
            notes.append(
                f"한국 {counts['KR']}개 — KOSPI 200 구성 종목 (pykrx는 KRX 자격증명이 필요하여 "
                f"위키피디아 목록 + Yahoo Finance로 분석)"
            )
        else:
            notes.append(
                f"한국 {counts['KR']}개 — 시가총액 {kr_cfg.get('min_market_cap', 0):,}원 이상 종목 중 "
                f"거래대금 상위 {kr_cfg.get('max_stocks', 0)}개 (pykrx 기준)"
            )
    if counts.get("US"):
        us_cfg = config.get("us", {})
        notes.append(
            f"미국 {counts['US']}개 — S&P 500 + NASDAQ 100 구성 종목 중 최대 {us_cfg.get('max_stocks', 0)}개"
        )
    if counts.get("JP"):
        notes.append(
            f"일본 {counts['JP']}개 — Nikkei 225 구성 종목 (일본어 위키피디아 목록 기준)"
        )
    return notes


def _load_recipients() -> list[str]:
    """Merge recipients from config/recipients.txt and REPORT_EMAIL env."""
    emails = []
    rcpt_file = DATA_DIR.parent / "config" / "recipients.txt"
    if rcpt_file.exists():
        for line in rcpt_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "@" in line:
                emails.append(line)
    raw = os.environ.get("REPORT_EMAIL", "")
    emails.extend(e.strip() for e in raw.replace(";", ",").split(",") if e.strip())
    # dedupe, preserve order
    return list(dict.fromkeys(emails))


def run(send_email: bool = False, news_max_tickers: int = 50, config_path: str | Path = CONFIG_PATH) -> bool:
    _load_dotenv()
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

    # Fill in real company names collected from yfinance info
    if not opinion_df.empty and "name" in opinion_df.columns:
        name_map = opinion_df.dropna(subset=["name"]).set_index("ticker")["name"].to_dict()

        def _fix_name(row):
            n = str(row["name"])
            if n == str(row["ticker"]) or n == str(row["ticker"]).split(".")[0]:
                return name_map.get(row["ticker"], n)
            return n

        tech_df["name"] = tech_df.apply(_fix_name, axis=1)

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

    logger.info("=== 6/6 AI commentary & building report ===")
    commentary = {}
    if ai_available():
        translate_jp_names(picks)
        commentary = generate_commentary(picks)
    universe_notes = _describe_universe(prices, config_path)
    html = build_report(
        composite_df,
        picks,
        scoring_config,
        universe_notes=universe_notes,
        commentary=commentary,
        ai_model_label=MODEL_LABEL if commentary else None,
    )
    report_path = DATA_DIR / f"report_{stamp}.html"
    report_path.write_text(html, encoding="utf-8")
    logger.info("Report saved: %s", report_path)

    pdf_path = build_pdf(report_path)

    if send_email:
        subject = f"[MONEYTREND 일일 종목 분석 리포트] {datetime.today().strftime('%Y-%m-%d')}"
        text_body = build_text_report(picks, universe_notes=universe_notes, commentary=commentary)
        attachments = [pdf_path] if pdf_path else []
        return send_report_email(subject, html, recipients=_load_recipients(), text_body=text_body, attachments=attachments)
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
