"""
Fundamental analysis module.
Combines IB consensus, price target gap, news sentiment and sector momentum
into a 0-100 fundamental score per ticker.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NEUTRAL = 50.0


def _clip_score(value, low: float, high: float, neutral: float = NEUTRAL) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return neutral
    return float(np.clip((value - low) / (high - low) * 100, 0, 100))


def compute_fundamental_scores(
    opinion_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    tech_df: pd.DataFrame,
    scoring_config: dict,
) -> pd.DataFrame:
    """
    Merge opinion / sentiment / sector momentum onto the technical table
    and compute the fundamental score (0-100).
    """
    if tech_df.empty:
        return pd.DataFrame()

    fund_cfg = scoring_config.get("fundamental", {})
    w_ib = fund_cfg.get("ib_opinion_weight", 40)
    w_gap = fund_cfg.get("target_price_gap_weight", 30)
    w_news = fund_cfg.get("news_sentiment_weight", 20)
    w_sector = fund_cfg.get("sector_momentum_weight", 10)

    df = tech_df[["ticker", "country", "ret_20d"]].copy()

    # --- IB opinion ---
    if not opinion_df.empty:
        df = df.merge(
            opinion_df[["ticker", "target_price", "target_gap_pct", "consensus_score", "upgrade_count", "downgrade_count"]],
            on="ticker",
            how="left",
        )
    else:
        df["target_price"] = np.nan
        df["target_gap_pct"] = np.nan
        df["consensus_score"] = np.nan
        df["upgrade_count"] = 0
        df["downgrade_count"] = 0

    # consensus 1-5 -> 0-100, plus upgrade/downgrade adjustment (+-5 each, capped)
    df["ib_score"] = df["consensus_score"].apply(
        lambda v: _clip_score(v, 1.0, 5.0) if pd.notna(v) else NEUTRAL
    )
    adj = (df["upgrade_count"].fillna(0) - df["downgrade_count"].fillna(0)) * 5
    df["ib_score"] = (df["ib_score"] + adj).clip(0, 100)

    # target gap: -20% .. +40% -> 0..100
    df["target_gap_score"] = df["target_gap_pct"].apply(lambda v: _clip_score(v, -20, 40))

    # --- News sentiment ---
    if not sentiment_df.empty:
        df = df.merge(sentiment_df[["ticker", "sentiment_score", "news_count"]], on="ticker", how="left")
    else:
        df["sentiment_score"] = np.nan
        df["news_count"] = 0
    df["news_score"] = df["sentiment_score"].fillna(NEUTRAL)
    df["news_count"] = df["news_count"].fillna(0).astype(int)

    # --- Sector momentum proxy: average 20d return of same-country peers ---
    country_ret = df.groupby("country")["ret_20d"].transform("mean")
    df["sector_momentum_pct"] = country_ret
    df["sector_score"] = country_ret.apply(lambda v: _clip_score(v, -10, 10))

    total_w = w_ib + w_gap + w_news + w_sector
    df["fundamental_score"] = (
        w_ib * df["ib_score"]
        + w_gap * df["target_gap_score"]
        + w_news * df["news_score"]
        + w_sector * df["sector_score"]
    ) / total_w
    df["fundamental_score"] = df["fundamental_score"].round(1)

    keep = [
        "ticker",
        "country",
        "target_price",
        "target_gap_pct",
        "consensus_score",
        "upgrade_count",
        "downgrade_count",
        "news_count",
        "sentiment_score",
        "sector_momentum_pct",
        "ib_score",
        "target_gap_score",
        "news_score",
        "sector_score",
        "fundamental_score",
    ]
    out = df[[c for c in keep if c in df.columns]]
    logger.info("Fundamental scores computed for %d tickers", len(out))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tech = pd.DataFrame(
        [
            {"ticker": "AAPL", "country": "US", "ret_20d": 5.0},
            {"ticker": "MSFT", "country": "US", "ret_20d": 3.0},
        ]
    )
    op = pd.DataFrame(
        [
            {"ticker": "AAPL", "target_price": 200.0, "target_gap_pct": 11.0, "consensus_score": 4.2, "upgrade_count": 2, "downgrade_count": 0},
        ]
    )
    sent = pd.DataFrame([{"ticker": "AAPL", "sentiment_score": 80.0, "news_count": 5}])
    print(compute_fundamental_scores(op, sent, tech, {}).T)
