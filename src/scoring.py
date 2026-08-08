"""
Composite scoring and ranking.
Combines technical (40%) and fundamental (60%) scores and picks top stocks.
"""

import logging
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

SCORING_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring.yaml"


def load_scoring_config(path: str | Path = SCORING_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_composite(tech_df: pd.DataFrame, fund_df: pd.DataFrame, scoring_config: dict) -> pd.DataFrame:
    """Merge technical and fundamental tables and compute the composite score."""
    if tech_df.empty:
        return pd.DataFrame()

    comp_cfg = scoring_config.get("composite", {})
    tech_ratio = comp_cfg.get("technical_ratio", 0.4)
    fund_ratio = comp_cfg.get("fundamental_ratio", 0.6)

    df = tech_df.copy()
    if not fund_df.empty:
        df = df.merge(fund_df.drop(columns=["country"], errors="ignore"), on="ticker", how="left")
        df["fundamental_score"] = df["fundamental_score"].fillna(50.0)
    else:
        df["fundamental_score"] = 50.0

    df["composite_score"] = (tech_ratio * df["technical_score"] + fund_ratio * df["fundamental_score"]).round(1)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    logger.info("Composite scores built for %d tickers", len(df))
    return df


COUNTRY_ORDER = ["KR", "US", "JP"]


def rank_picks(composite_df: pd.DataFrame, scoring_config: dict) -> dict:
    """
    Pick top stocks per country for short-term / long-term horizons.
    Returns {"short": {country: df}, "long": {country: df}, "markets": df}.
    """
    rank_cfg = scoring_config.get("ranking", {})
    n_short = rank_cfg.get("short_term_top_n", 10)
    n_long = rank_cfg.get("long_term_top_n", 10)

    result = {"short": {}, "long": {}, "markets": pd.DataFrame()}
    if composite_df.empty:
        return result

    for country, g in composite_df.groupby("country"):
        result["short"][country] = g.sort_values(
            ["short_term_score", "composite_score"], ascending=False
        ).head(n_short)
        result["long"][country] = g.sort_values(
            ["long_term_score", "composite_score"], ascending=False
        ).head(n_long)

    # stable country display order
    result["short"] = {c: result["short"][c] for c in COUNTRY_ORDER if c in result["short"]}
    result["long"] = {c: result["long"][c] for c in COUNTRY_ORDER if c in result["long"]}

    markets = (
        composite_df.groupby("country")
        .agg(
            avg_composite=("composite_score", "mean"),
            avg_ret_20d=("ret_20d", "mean"),
            count=("ticker", "count"),
        )
        .round(2)
        .sort_values("avg_composite", ascending=False)
        .reset_index()
    )
    result["markets"] = markets
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tech = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "country": ["US", "US", "KR"],
            "name": ["A Co", "B Co", "C Co"],
            "close": [100, 200, 300],
            "ret_20d": [5.0, -2.0, 1.0],
            "technical_score": [70.0, 40.0, 55.0],
            "short_term_score": [72.0, 38.0, 50.0],
            "long_term_score": [65.0, 45.0, 60.0],
        }
    )
    fund = pd.DataFrame({"ticker": ["A", "B", "C"], "fundamental_score": [80.0, 50.0, 60.0]})
    comp = build_composite(tech, fund, {})
    print(comp)
    picks = rank_picks(comp, {"ranking": {"short_term_top_n": 2, "long_term_top_n": 2}})
    for horizon in ("short", "long"):
        for country, df in picks[horizon].items():
            print(f"--- {horizon}/{country} ---")
            print(df[["ticker", "composite_score"]])
