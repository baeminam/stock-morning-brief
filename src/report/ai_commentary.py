"""
AI commentary via Groq free tier (OpenAI-compatible API).
Generates 2-3 sentence Korean commentary per recommended stock.
Falls back silently when GROQ_API_KEY is not set or calls fail.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
MODEL_LABEL = "Llama 3.3 70B (Groq 무료 티어)"


def is_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _fmt(value, digits=1):
    try:
        return f"{float(value):+.{digits}f}" if digits else f"{float(value):.0f}"
    except (TypeError, ValueError):
        return "-"


def _build_prompt(rec: dict, horizon: str) -> str:
    horizon_text = "단기(수 일~수 주)" if horizon == "short" else "장기(2~3년)"
    lines = [
        f"종목: {rec.get('name')} ({rec.get('ticker')}), 시장: {rec.get('country')}",
        f"현재가: {_fmt(rec.get('close'), 2)}",
        f"20일 수익률: {_fmt(rec.get('ret_20d'))}%, 60일 수익률: {_fmt(rec.get('ret_60d'))}%",
        f"RSI(14): {_fmt(rec.get('rsi14'))}, MACD 히스토그램: {_fmt(rec.get('macd_hist_pct'), 3)}%",
        f"거래량 20일 평균 대비: {_fmt(rec.get('vol_ratio'))}배",
        f"기술 점수: {_fmt(rec.get('technical_score'))}/100, 기본 점수: {_fmt(rec.get('fundamental_score'))}/100, 종합: {_fmt(rec.get('composite_score'))}/100",
    ]
    gap = rec.get("target_gap_pct")
    if gap is not None and gap == gap:  # not NaN
        lines.append(f"애널리스트 평균 목표가 대비 괴리: {_fmt(gap)}%")
    cons = rec.get("consensus_score")
    if cons is not None and cons == cons:
        lines.append(f"IB 컨센서스: {_fmt(cons)}/5 (5=강력매수)")

    data = "\n".join(lines)
    return (
        f"다음은 주식 종목의 정량 지표입니다. {horizon_text} 관점 투자 참고 해설을 "
        f"한국어 2~3문장으로 작성해 주세요. 지표에 근거해 구체적으로 쓰되, "
        f"'투자 권유가 아닌 참고 정보'임을 자연스럽게 녹여 주세요. 숫자 인용 가능.\n\n{data}"
    )


def _call_groq(prompt: str, api_key: str, timeout: int = 30, max_retries: int = 3) -> str | None:
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 300,
                },
                timeout=timeout,
            )
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 20))
                wait = min(retry_after, 60) * (attempt + 1)
                logger.info("Groq rate limited; waiting %.0fs (attempt %d)", wait, attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("Groq commentary call failed: %s", e)
            return None
    logger.warning("Groq call gave up after retries (rate limit)")
    return None


def generate_commentary(picks: dict, sleep_sec: float = 2.2) -> dict:
    """
    Generate AI commentary for all per-country picks.
    picks: {"short": {country: df}, "long": {country: df}, ...}
    Returns {(ticker, horizon): commentary_text}. Empty dict when unavailable.
    sleep_sec: Groq free tier is 30 RPM for llama-3.3-70b — keep ~25 RPM max.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.info("GROQ_API_KEY not set; skipping AI commentary")
        return {}

    tasks = []
    seen = set()
    for horizon in ("short", "long"):
        for country, df in picks.get(horizon, {}).items():
            for rec in df.to_dict("records"):
                key = (rec.get("ticker"), horizon)
                if key not in seen:
                    seen.add(key)
                    tasks.append((key, rec, horizon))

    logger.info("Generating AI commentary for %d stock-horizon pairs", len(tasks))
    out = {}
    for key, rec, horizon in tasks:
        text = _call_groq(_build_prompt(rec, horizon), api_key)
        if text:
            out[key] = text
        time.sleep(sleep_sec)
    logger.info("AI commentary generated: %d/%d", len(out), len(tasks))
    return out


def translate_jp_names(picks: dict) -> int:
    """
    Translate Japanese company names in JP picks to Korean via one batched
    Groq call. Mutates the DataFrames in place. Returns number translated.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return 0

    names = set()
    for horizon in ("short", "long"):
        df = picks.get(horizon, {}).get("JP")
        if df is not None and not df.empty:
            names.update(df["name"].astype(str))
    if not names:
        return 0

    import json

    name_list = sorted(names)
    prompt = (
        "다음은 일본 기업명 목록입니다. 각각 한국어 표기(한국에서 통용되는 이름, "
        "없으면 자연스러운 음역)로 번역해서, 입력과 같은 순서의 JSON 배열로만 답해 주세요. "
        "다른 설명 없이 JSON 목록만 출력하세요.\n\n" + json.dumps(name_list, ensure_ascii=False)

    )
    text = _call_groq(prompt, api_key)
    if not text:
        return 0

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        translated = json.loads(text[start:end])
        mapping = {ja: ko for ja, ko in zip(name_list, translated) if isinstance(ko, str)}
    except Exception as e:
        logger.warning("JP name translation parse failed: %s", e)
        return 0

    count = 0
    for horizon in ("short", "long"):
        df = picks.get(horizon, {}).get("JP")
        if df is not None and not df.empty:
            before = df["name"].copy()
            df["name"] = df["name"].astype(str).map(lambda n: mapping.get(n, n))
            count += int((before != df["name"]).sum())
    logger.info("JP names translated to Korean: %d rows", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = {
        "ticker": "005930.KS", "name": "삼성전자", "country": "KR", "close": 70000,
        "ret_20d": 3.2, "ret_60d": 8.1, "rsi14": 58.0, "macd_hist_pct": 0.12,
        "vol_ratio": 1.8, "technical_score": 68.0, "fundamental_score": 74.0,
        "composite_score": 71.6, "target_gap_pct": 15.2, "consensus_score": 4.2,
    }
    import pandas as pd

    df = pd.DataFrame([sample])
    picks = {"short": {"KR": df}, "long": {"KR": df}}
    print(generate_commentary(picks))
