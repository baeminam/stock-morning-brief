"""
Price data collection module.
Supports Korean stocks via pykrx and US/JP stocks via yfinance.
"""

import os
import time
import logging
import io
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
import yaml

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "universe.yaml"


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _today_str() -> str:
    return datetime.today().strftime("%Y%m%d")


def _n_days_ago_str(days: int) -> str:
    return (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")


def _find_recent_kr_business_day(ref_date: datetime | None = None, max_lookback: int = 10) -> str:
    """Find the most recent Korean trading day by trying pykrx."""
    from pykrx import stock

    ref = ref_date or datetime.today()
    for i in range(max_lookback):
        d = ref - timedelta(days=i)
        d_str = d.strftime("%Y%m%d")
        try:
            sample = stock.get_market_ticker_list(d_str)
            if sample:
                return d_str
        except Exception:
            continue
    # fallback
    return (ref - timedelta(days=1)).strftime("%Y%m%d")


def get_kr_universe(config: dict) -> list[dict]:
    """Return Korean stock universe with name and ticker."""
    from pykrx import stock

    cfg = config.get("kr", {})
    if not cfg.get("enabled", False):
        return []

    max_stocks = cfg.get("max_stocks", 300)
    min_market_cap = cfg.get("min_market_cap", 100_000_000_000)

    base_day = _find_recent_kr_business_day()
    logger.info("Using Korean base day: %s", base_day)

    try:
        cap_df = stock.get_market_cap_by_ticker(base_day)
        if cap_df is None or cap_df.empty:
            logger.warning("Empty market cap data from pykrx; fallback to ohlcv ticker list")
            tickers = stock.get_market_ticker_list(base_day)
            return [{"ticker": t, "name": stock.get_market_ticker_name(t), "country": "KR"} for t in tickers[:max_stocks]]

        cap_df = cap_df.reset_index()
        # Columns may be named differently across pykrx versions; try common names
        ticker_col = "티커" if "티커" in cap_df.columns else "종목코드" if "종목코드" in cap_df.columns else cap_df.columns[0]
        cap_col = "시가총액" if "시가총액" in cap_df.columns else None
        amount_col = "거래대금" if "거래대금" in cap_df.columns else None

        filtered = cap_df
        if cap_col:
            filtered = filtered[filtered[cap_col] >= min_market_cap]
        if amount_col:
            filtered = filtered.sort_values(by=amount_col, ascending=False)

        tickers = filtered[ticker_col].astype(str).str.zfill(6).unique().tolist()[:max_stocks]
        universe = []
        for t in tickers:
            try:
                name = stock.get_market_ticker_name(t)
            except Exception:
                name = t
            universe.append({"ticker": t, "name": name, "country": "KR"})
        return universe
    except Exception as e:
        logger.error("Failed to load Korean universe: %s", e)
        return []


def get_us_universe(config: dict) -> list[dict]:
    """Return US stock universe from S&P 500 and NASDAQ 100."""
    cfg = config.get("us", {})
    if not cfg.get("enabled", False):
        return []

    max_stocks = cfg.get("max_stocks", 500)
    indices = cfg.get("indices", ["^GSPC", "^IXIC"])

    # S&P 500 and NASDAQ-100 component lists from Wikipedia
    symbols = set()
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=HTTP_HEADERS, timeout=15,
        ).text
        sp500 = pd.read_html(io.StringIO(html))[0]
        symbols.update(sp500["Symbol"].astype(str).tolist())
    except Exception as e:
        logger.warning("Failed to fetch S&P 500 list: %s", e)

    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers=HTTP_HEADERS, timeout=15,
        ).text
        ndx_tables = pd.read_html(io.StringIO(html))
        for tbl in ndx_tables:
            cols = [c for c in tbl.columns if "Ticker" in str(c) or "Symbol" in str(c)]
            if cols:
                symbols.update(tbl[cols[0]].astype(str).tolist())
    except Exception as e:
        logger.warning("Failed to fetch NASDAQ-100 list: %s", e)

    # Exclude index tickers; yfinance uses '-' instead of '.' (e.g. BRK.B -> BRK-B)
    symbols = {s.strip().upper().replace(".", "-") for s in symbols if s and not s.startswith("^")}
    symbols = sorted(list(symbols))[:max_stocks]

    universe = []
    for s in symbols:
        universe.append({"ticker": s, "name": s, "country": "US"})
    return universe


def get_jp_universe(config: dict) -> list[dict]:
    """Return Japanese stock universe from config tickers."""
    cfg = config.get("jp", {})
    if not cfg.get("enabled", False):
        return []

    tickers = cfg.get("tickers", [])
    max_stocks = cfg.get("max_stocks", len(tickers))
    tickers = tickers[:max_stocks]
    return [{"ticker": t, "name": t, "country": "JP"} for t in tickers]


def fetch_kr_prices(universe: list[dict], lookback_days: int) -> pd.DataFrame:
    """Fetch OHLCV for Korean stocks using pykrx."""
    from pykrx import stock

    end = _find_recent_kr_business_day()
    start = _n_days_ago_str(lookback_days)

    records = []
    for item in universe:
        ticker = item["ticker"]
        try:
            df = stock.get_market_ohlcv_by_date(start, end, ticker)
            if df is None or df.empty:
                continue
            df = df.reset_index()
            df = df.rename(
                columns={
                    "시가": "open",
                    "고가": "high",
                    "저가": "low",
                    "종가": "close",
                    "거래량": "volume",
                    "등락률": "change_pct",
                }
            )
            df["ticker"] = ticker
            df["name"] = item.get("name", ticker)
            df["country"] = "KR"
            # keep only standard columns
            keep = ["date", "ticker", "name", "country", "open", "high", "low", "close", "volume"]
            df = df[[c for c in keep if c in df.columns]]
            records.append(df)
        except Exception as e:
            logger.debug("KR price fetch failed for %s: %s", ticker, e)
    if not records:
        return pd.DataFrame()
    return pd.concat(records, ignore_index=True)


def fetch_yf_prices(universe: list[dict], lookback_days: int, country: str) -> pd.DataFrame:
    """Fetch OHLCV for US/JP stocks using yfinance batch download."""
    if not universe:
        return pd.DataFrame()

    tickers = [item["ticker"] for item in universe]
    end = datetime.today()
    start = end - timedelta(days=lookback_days)

    try:
        data = yf.download(
            tickers=tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=True,
        )
    except Exception as e:
        logger.error("yfinance batch download failed for %s: %s", country, e)
        return pd.DataFrame()

    records = []
    name_map = {item["ticker"]: item.get("name", item["ticker"]) for item in universe}

    # yfinance multi-ticker returns MultiIndex columns
    if isinstance(data.columns, pd.MultiIndex):
        valid_tickers = [t for t in tickers if t in data.columns.levels[0]]
        for ticker in valid_tickers:
            try:
                sub = data[ticker].copy()
                sub = sub.dropna(how="all")
                if sub.empty:
                    continue
                sub = sub.reset_index()
                sub["ticker"] = ticker
                sub["name"] = name_map.get(ticker, ticker)
                sub["country"] = country
                sub = sub.rename(
                    columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Adj Close": "adj_close",
                        "Volume": "volume",
                    }
                )
                # If auto_adjust=True, only Close/Volume are present
                for col in ["open", "high", "low", "close", "volume"]:
                    if col not in sub.columns:
                        sub[col] = sub.get("close", sub.get("Volume"))
                keep = ["Date", "ticker", "name", "country", "open", "high", "low", "close", "volume"]
                sub = sub[[c for c in keep if c in sub.columns]]
                sub = sub.rename(columns={"Date": "date"})
                records.append(sub)
            except Exception as e:
                logger.debug("yf price parse failed for %s: %s", ticker, e)
    else:
        # Single ticker returned flat DataFrame
        ticker = tickers[0]
        try:
            sub = data.reset_index()
            sub["ticker"] = ticker
            sub["name"] = name_map.get(ticker, ticker)
            sub["country"] = country
            sub = sub.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                }
            )
            keep = ["Date", "ticker", "name", "country", "open", "high", "low", "close", "volume"]
            sub = sub[[c for c in keep if c in sub.columns]]
            sub = sub.rename(columns={"Date": "date"})
            records.append(sub)
        except Exception as e:
            logger.debug("yf single price parse failed for %s: %s", ticker, e)

    if not records:
        return pd.DataFrame()
    return pd.concat(records, ignore_index=True)


def enrich_us_jp_names(universe: list[dict], sleep_sec: float = 0.5) -> list[dict]:
    """Try to fetch short names for US/JP tickers using yfinance Ticker.info."""
    enriched = []
    for item in universe:
        ticker = item["ticker"]
        name = ticker
        try:
            info = yf.Ticker(ticker).info
            name = info.get("shortName") or info.get("longName") or ticker
        except Exception as e:
            logger.debug("Name fetch failed for %s: %s", ticker, e)
        enriched.append({**item, "name": name})
        time.sleep(sleep_sec)
    return enriched


def fetch_all_prices(config_path: str | Path = CONFIG_PATH, enrich_names: bool = False) -> pd.DataFrame:
    config = load_config(config_path)

    kr_uni = get_kr_universe(config)
    us_uni = get_us_universe(config)
    jp_uni = get_jp_universe(config)

    # Recent pykrx versions require KRX credentials; fall back to a curated
    # yfinance-based Korean universe when pykrx is unavailable.
    kr_via_yf = False
    if not kr_uni:
        kr_cfg = config.get("kr", {})
        fallback = kr_cfg.get("fallback_tickers", [])
        if kr_cfg.get("enabled", False) and fallback:
            max_stocks = kr_cfg.get("max_stocks", len(fallback))
            kr_uni = [
                {"ticker": f"{t}.KS", "name": t, "country": "KR"}
                for t in fallback[:max_stocks]
            ]
            kr_via_yf = True
            logger.info("KR universe via yfinance fallback: %d tickers", len(kr_uni))

    logger.info("Universes: KR=%d US=%d JP=%d", len(kr_uni), len(us_uni), len(jp_uni))

    if enrich_names:
        us_uni = enrich_us_jp_names(us_uni)
        jp_uni = enrich_us_jp_names(jp_uni)

    frames = []
    if kr_uni:
        if kr_via_yf:
            frames.append(fetch_yf_prices(kr_uni, config["kr"]["lookback_days"], "KR"))
        else:
            frames.append(fetch_kr_prices(kr_uni, config["kr"]["lookback_days"]))
    if us_uni:
        frames.append(fetch_yf_prices(us_uni, config["us"]["lookback_days"], "US"))
    if jp_uni:
        frames.append(fetch_yf_prices(jp_uni, config["jp"]["lookback_days"], "JP"))

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prices = fetch_all_prices(enrich_names=False)
    print(prices.head())
    print("Shape:", prices.shape)
    print("Countries:", prices["country"].value_counts())
