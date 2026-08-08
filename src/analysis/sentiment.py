"""
News sentiment analysis module.
Scores news titles with keyword matching (config/keywords.yaml).
Output: 0-100 sentiment score per ticker (50 = neutral / no news).
"""

import logging
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "config" / "keywords.yaml"


def load_keywords(path: str | Path = KEYWORDS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def score_title(title: str, positive: list[str], negative: list[str]) -> tuple[int, int]:
    """Count positive/negative keyword hits in a title."""
    pos = sum(1 for kw in positive if kw and kw in title)
    neg = sum(1 for kw in negative if kw and kw in title)
    return pos, neg


def score_news(news_df: pd.DataFrame, keywords: dict | None = None) -> pd.DataFrame:
    """
    Aggregate keyword sentiment per ticker.
    Returns DataFrame with ticker, news_count, pos_count, neg_count, sentiment_score (0-100).
    """
    keywords = keywords or load_keywords()
    positive = keywords.get("positive", [])
    negative = keywords.get("negative", [])

    if news_df.empty:
        return pd.DataFrame(columns=["ticker", "news_count", "pos_count", "neg_count", "sentiment_score"])

    rows = []
    for ticker, g in news_df.groupby("ticker"):
        pos_total = 0
        neg_total = 0
        for title in g["title"].astype(str):
            p, n = score_title(title, positive, negative)
            pos_total += p
            neg_total += n
        count = len(g)
        total_hits = pos_total + neg_total
        if total_hits == 0:
            score = 50.0
        else:
            # net sentiment ratio mapped to 0-100
            score = (pos_total / total_hits) * 100
        rows.append(
            {
                "ticker": ticker,
                "news_count": count,
                "pos_count": pos_total,
                "neg_count": neg_total,
                "sentiment_score": round(score, 1),
            }
        )

    df = pd.DataFrame(rows)
    logger.info("Sentiment scored for %d tickers", len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = pd.DataFrame(
        [
            {"ticker": "005930", "title": "삼성전자 영업이익 급증, 목표가 상향"},
            {"ticker": "005930", "title": "외국인 매수 확대"},
            {"ticker": "AAPL", "title": "Apple stock falls amid lawsuit concerns"},  # no KR keyword hit -> neutral
        ]
    )
    print(score_news(sample))
