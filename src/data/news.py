"""
News collection module.
Korean stocks: Naver Finance item news (scraping, polite sleep).
US/JP stocks: yfinance ticker news.
"""

import logging
import time
from datetime import datetime

import pandas as pd
import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_kr_news(ticker: str, max_items: int = 5, sleep_sec: float = 0.5) -> list[dict]:
    """Fetch recent news titles for a Korean stock via Naver mobile JSON API.
    Accepts both 6-digit codes and yfinance-style tickers (005930.KS)."""
    import html as html_lib

    code = ticker.split(".")[0]
    url = f"https://m.stock.naver.com/api/news/stock/{code}?pageSize={max_items}&page=1"
    rows = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        groups = resp.json()
        for group in groups if isinstance(groups, list) else []:
            for item in group.get("items", []):
                title = html_lib.unescape(str(item.get("titleFull") or item.get("title") or "")).strip()
                if not title:
                    continue
                dt = str(item.get("datetime", ""))
                date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt) >= 8 else datetime.today().strftime("%Y-%m-%d")
                rows.append(
                    {
                        "ticker": ticker,
                        "country": "KR",
                        "title": title,
                        "publisher": item.get("officeName") or "naver",
                        "date": date,
                    }
                )
                if len(rows) >= max_items:
                    break
            if len(rows) >= max_items:
                break
    except Exception as e:
        logger.debug("KR news fetch failed for %s: %s", ticker, e)
    time.sleep(sleep_sec)
    return rows


def fetch_yf_news(ticker: str, country: str, max_items: int = 5, sleep_sec: float = 0.3) -> list[dict]:
    """Fetch recent news titles for a US/JP stock from yfinance."""
    import yfinance as yf

    rows = []
    try:
        news = yf.Ticker(ticker).news or []
        for item in news[:max_items]:
            # yfinance >= 0.2.31 nests fields under "content"
            content = item.get("content", item)
            title = content.get("title")
            if not title:
                continue
            publisher = content.get("publisher")
            if isinstance(publisher, dict):
                publisher = publisher.get("displayName")
            if not publisher:
                provider = content.get("provider")
                publisher = provider.get("displayName") if isinstance(provider, dict) else provider
            rows.append(
                {
                    "ticker": ticker,
                    "country": country,
                    "title": str(title),
                    "publisher": publisher or "yfinance",
                    "date": datetime.today().strftime("%Y-%m-%d"),
                }
            )
    except Exception as e:
        logger.debug("yf news fetch failed for %s: %s", ticker, e)
    time.sleep(sleep_sec)
    return rows


def fetch_all_news(
    price_df: pd.DataFrame,
    max_per_ticker: int = 5,
    max_tickers: int | None = None,
    sleep_sec: float = 0.3,
) -> pd.DataFrame:
    """
    Fetch news titles for each ticker in the price DataFrame.
    max_tickers limits how many tickers to query (most recent first by volume*close).
    """
    if price_df.empty:
        return pd.DataFrame(columns=["ticker", "country", "title", "publisher", "date"])

    latest = price_df.sort_values("date").groupby(["ticker", "country"]).last().reset_index()
    # Prioritize high-turnover tickers to keep runtime bounded
    latest["_turnover"] = latest["close"].fillna(0) * latest["volume"].fillna(0)
    latest = latest.sort_values("_turnover", ascending=False)
    if max_tickers:
        latest = latest.head(max_tickers)

    rows = []
    for _, row in latest.iterrows():
        ticker = row["ticker"]
        country = row["country"]
        if country == "KR":
            rows.extend(fetch_kr_news(ticker, max_per_ticker, sleep_sec))
        else:
            rows.extend(fetch_yf_news(ticker, country, max_per_ticker, sleep_sec))

    logger.info("Fetched %d news rows for %d tickers", len(rows), len(latest))
    return pd.DataFrame(rows, columns=["ticker", "country", "title", "publisher", "date"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = pd.DataFrame(
        [
            {"ticker": "005930", "country": "KR", "date": datetime.today(), "close": 70000, "volume": 1000000},
            {"ticker": "AAPL", "country": "US", "date": datetime.today(), "close": 180, "volume": 50000000},
        ]
    )
    df = fetch_all_news(sample, max_per_ticker=3)
    print(df)
