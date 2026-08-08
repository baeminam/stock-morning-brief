"""
Technical analysis module.
Computes RSI, MACD, moving averages, Bollinger Bands, volume surge
and converts them into 0-100 scores per ticker.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    if loss.iloc[-1] == 0 or np.isnan(loss.iloc[-1]):
        return None
    rs = gain.iloc[-1] / loss.iloc[-1]
    return 100 - 100 / (1 + rs)


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> float | None:
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    price = close.iloc[-1]
    if not price:
        return None
    # normalize by price to make it comparable across tickers
    return float(hist.iloc[-1] / price * 100)


def _clip_score(value: float | None, low: float, high: float, neutral: float = 50.0) -> float:
    """Map value in [low, high] to [0, 100]. NaN -> neutral."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return neutral
    return float(np.clip((value - low) / (high - low) * 100, 0, 100))


def _rsi_score(rsi: float | None) -> float:
    """Favor moderately strong momentum; penalize overbought/oversold extremes."""
    if rsi is None or np.isnan(rsi):
        return 50.0
    if rsi <= 30:
        return 60.0  # oversold: rebound candidate
    if rsi <= 55:
        return 60 + (rsi - 30) / 25 * 40  # 30->60, 55->100
    if rsi <= 70:
        return 100 - (rsi - 55) / 15 * 40  # 55->100, 70->60
    return max(0.0, 60 - (rsi - 70) * 3)  # overbought penalty


def _bollinger_score(pctb: float | None) -> float:
    """Favor mid-band momentum; extremes are risky."""
    if pctb is None or np.isnan(pctb):
        return 50.0
    return float(np.clip(100 - abs(pctb - 0.55) * 160, 0, 100))


def compute_technical_scores(price_df: pd.DataFrame, scoring_config: dict) -> pd.DataFrame:
    """
    Compute technical indicators and scores for each ticker.
    Returns one row per ticker with indicator values and scores (0-100).
    """
    if price_df.empty:
        return pd.DataFrame()

    tech_cfg = scoring_config.get("technical", {})
    w_rsi = tech_cfg.get("rsi_weight", 30)
    w_macd = tech_cfg.get("macd_weight", 25)
    w_ma = tech_cfg.get("ma_weight", 20)
    w_bb = tech_cfg.get("bollinger_weight", 15)
    w_vol = tech_cfg.get("volume_weight", 10)

    rows = []
    for (ticker, country), g in price_df.groupby(["ticker", "country"]):
        g = g.sort_values("date")
        close = g["close"].astype(float)
        volume = g["volume"].astype(float)
        high = g["high"].astype(float)
        low = g["low"].astype(float)
        if len(close) < 20:
            continue

        last_close = close.iloc[-1]
        name = g["name"].iloc[-1]

        # Indicators
        rsi = _rsi(close)
        macd_hist = _macd_hist(close)

        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
        ma20_ratio = (last_close / ma20 - 1) * 100 if ma20 else None
        ma60_ratio = (last_close / ma60 - 1) * 100 if ma60 else None

        std20 = close.rolling(20).std().iloc[-1]
        pctb = None
        if ma20 and std20 and not np.isnan(std20) and std20 > 0:
            pctb = (last_close - (ma20 - 2 * std20)) / (4 * std20)

        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        vol_ratio = float(volume.iloc[-1] / vol_ma20) if vol_ma20 else None

        ret_5d = (last_close / close.iloc[-6] - 1) * 100 if len(close) >= 6 else None
        ret_20d = (last_close / close.iloc[-21] - 1) * 100 if len(close) >= 21 else None
        ret_60d = (last_close / close.iloc[-61] - 1) * 100 if len(close) >= 61 else None

        # Sub-scores (0-100)
        s_rsi = _rsi_score(rsi)
        s_macd = _clip_score(macd_hist, -1.0, 1.0)
        s_ma = _clip_score(ma20_ratio, -10, 10)
        s_bb = _bollinger_score(pctb)
        s_vol = _clip_score(vol_ratio, 0.5, 3.0)

        total_w = w_rsi + w_macd + w_ma + w_bb + w_vol
        short_term_score = (
            w_rsi * s_rsi + w_macd * s_macd + w_ma * s_ma + w_bb * s_bb + w_vol * s_vol
        ) / total_w

        # Long-term: trend over 60d horizon
        s_ma60 = _clip_score(ma60_ratio, -20, 20)
        s_ret60 = _clip_score(ret_60d, -30, 30)
        s_trend = _clip_score(ma20_ratio - ma60_ratio if (ma20_ratio is not None and ma60_ratio is not None) else None, -15, 15)
        long_term_score = 0.4 * s_ma60 + 0.4 * s_ret60 + 0.2 * s_trend

        technical_score = 0.6 * short_term_score + 0.4 * long_term_score

        rows.append(
            {
                "ticker": ticker,
                "country": country,
                "name": name,
                "close": last_close,
                "ret_5d": ret_5d,
                "ret_20d": ret_20d,
                "ret_60d": ret_60d,
                "rsi14": rsi,
                "macd_hist_pct": macd_hist,
                "ma20_ratio": ma20_ratio,
                "ma60_ratio": ma60_ratio,
                "bb_pctb": pctb,
                "vol_ratio": vol_ratio,
                "short_term_score": round(short_term_score, 1),
                "long_term_score": round(long_term_score, 1),
                "technical_score": round(technical_score, 1),
            }
        )

    df = pd.DataFrame(rows)
    logger.info("Technical scores computed for %d tickers", len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # synthetic uptrend test
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    base = np.linspace(100, 130, 120) + np.random.randn(120).cumsum() * 0.5
    sample = pd.DataFrame(
        {
            "date": dates,
            "ticker": "TEST",
            "name": "Test Co",
            "country": "US",
            "open": base,
            "high": base * 1.01,
            "low": base * 0.99,
            "close": base,
            "volume": np.random.randint(1_000_000, 3_000_000, 120),
        }
    )
    out = compute_technical_scores(sample, {})
    print(out.T)
