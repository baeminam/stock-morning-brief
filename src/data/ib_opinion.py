"""
IB / analyst opinion and price target collection.
Uses yfinance as primary source; falls back to neutral values when unavailable.
"""

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

GRADE_SCORES = {
    "strong buy": 5,
    "buy": 4,
    "outperform": 4,
    "overweight": 4,
    "market outperform": 4,
    "hold": 3,
    "neutral": 3,
    "equal-weight": 3,
    "market perform": 3,
    "underperform": 2,
    "underweight": 2,
    "market underperform": 2,
    "sell": 1,
    "strong sell": 1,
}


def _grade_to_score(grade: str | None) -> float | None:
    if not grade:
        return None
    return GRADE_SCORES.get(str(grade).strip().lower())


def _fetch_ticker_opinion(ticker: str, country: str, current_price: float | None = None, sleep_sec: float = 0.3):
    """Fetch yfinance recommendations and price target for a single ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        # yfinance >= 1.5 renamed analyst_price_target -> analyst_price_targets
        target_dict = getattr(t, "analyst_price_targets", None) or getattr(t, "analyst_price_target", None) or {}
        recs = t.recommendations

        # Price target
        # NOTE: 'current' in analyst_price_targets is the *current stock price*,
        # not the target — use mean/median instead.
        target_price = None
        if isinstance(target_dict, dict):
            target_price = target_dict.get("mean") or target_dict.get("median")
        elif isinstance(target_dict, pd.DataFrame):
            target_price = target_dict.iloc[0].get("mean") or target_dict.iloc[0].get("median")

        if not target_price:
            target_price = info.get("targetMeanPrice") or info.get("targetHighPrice")

        target_gap_pct = None
        if target_price and current_price:
            try:
                target_gap_pct = (float(target_price) - float(current_price)) / float(current_price) * 100
            except Exception:
                target_gap_pct = None

        # Consensus from recommendations summary if available
        consensus_score = None
        rec_summary = t.recommendations_summary
        if isinstance(rec_summary, pd.DataFrame) and not rec_summary.empty:
            latest = rec_summary.iloc[-1]
            weighted = (
                5 * float(latest.get("strongBuy", 0))
                + 4 * float(latest.get("buy", 0))
                + 3 * float(latest.get("hold", 0))
                + 2 * float(latest.get("sell", 0))
                + 1 * float(latest.get("strongSell", 0))
            )
            total = (
                float(latest.get("strongBuy", 0))
                + float(latest.get("buy", 0))
                + float(latest.get("hold", 0))
                + float(latest.get("sell", 0))
                + float(latest.get("strongSell", 0))
            )
            consensus_score = weighted / total if total > 0 else None

        # Recent recommendation changes
        upgrade_count = 0
        downgrade_count = 0
        if isinstance(recs, pd.DataFrame) and not recs.empty:
            cutoff = datetime.today() - timedelta(days=90)
            recs = recs.reset_index()
            date_col = "Date" if "Date" in recs.columns else recs.columns[0]
            recs[date_col] = pd.to_datetime(recs[date_col], errors="coerce")
            recent = recs[recs[date_col] >= cutoff]
            action_col = "Action" if "Action" in recent.columns else None
            if action_col:
                upgrade_count = int((recent[action_col] == "up").sum())
                downgrade_count = int((recent[action_col] == "down").sum())

        time.sleep(sleep_sec)
        return {
            "ticker": ticker,
            "country": country,
            "current_price": current_price,
            "target_price": target_price,
            "target_gap_pct": target_gap_pct,
            "consensus_score": consensus_score,
            "upgrade_count": upgrade_count,
            "downgrade_count": downgrade_count,
        }
    except Exception as e:
        logger.debug("IB opinion fetch failed for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "country": country,
            "current_price": current_price,
            "target_price": None,
            "target_gap_pct": None,
            "consensus_score": None,
            "upgrade_count": 0,
            "downgrade_count": 0,
        }


def fetch_ib_opinions(price_df: pd.DataFrame, sleep_sec: float = 0.3) -> pd.DataFrame:
    """
    Given a price DataFrame, fetch IB opinions for each ticker.
    Returns a DataFrame with opinion metrics.
    """
    if price_df.empty:
        return pd.DataFrame()

    latest = price_df.sort_values("date").groupby(["ticker", "country"]).last().reset_index()
    rows = []
    for _, row in latest.iterrows():
        ticker = row["ticker"]
        country = row["country"]
        current_price = row.get("close")
        rows.append(_fetch_ticker_opinion(ticker, country, current_price, sleep_sec))

    df = pd.DataFrame(rows)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # simple test with AAPL
    res = _fetch_ticker_opinion("AAPL", "US", current_price=180.0)
    print(res)
