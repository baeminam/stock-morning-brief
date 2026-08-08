"""
HTML report builder using Jinja2 template (templates/report.html).
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"

CURRENCY = {"KR": "₩", "US": "$", "JP": "¥"}


def _fmt_price(value, country: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    symbol = CURRENCY.get(country, "")
    if country == "KR":
        return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.2f}"


def _fmt_pct(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{value:+.1f}%"


def _fmt_num(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{value:.1f}"


def _make_reasons(rec: dict, horizon: str) -> list[str]:
    """Generate 2-3 line Korean recommendation reasons from indicator values."""
    tech_items = []
    fund_items = []

    rsi = rec.get("rsi14")
    if rsi is not None and not pd.isna(rsi):
        if rsi < 30:
            tech_items.append(f"RSI {rsi:.0f}로 과매도 구간 — 기술적 반등 후보")
        elif rsi <= 65:
            tech_items.append(f"RSI {rsi:.0f}로 과열 없는 상승 흐름")
        else:
            tech_items.append(f"RSI {rsi:.0f}로 단기 과열 — 변동성 주의")

    macd = rec.get("macd_hist_pct")
    if macd is not None and not pd.isna(macd) and macd > 0:
        tech_items.append("MACD 상승 신호 유지")

    vol = rec.get("vol_ratio")
    if vol is not None and not pd.isna(vol) and vol >= 1.5:
        tech_items.append(f"거래량 20일 평균 대비 {vol:.1f}배 급증")

    ret20 = rec.get("ret_20d")
    if ret20 is not None and not pd.isna(ret20):
        tech_items.append(f"최근 20일 수익률 {ret20:+.1f}%")

    gap = rec.get("target_gap_pct")
    if gap is not None and not pd.isna(gap):
        if gap > 5:
            fund_items.append(f"애널리스트 목표가 대비 +{gap:.0f}% 상승 여력")
        elif gap < -5:
            fund_items.append(f"목표가 대비 {gap:.0f}% — 목표가 근접/초과 구간")

    cons = rec.get("consensus_score")
    if cons is not None and not pd.isna(cons):
        label = "매수 우위" if cons >= 4 else "중립" if cons >= 3 else "비관 우위"
        fund_items.append(f"IB 컨센서스 {cons:.1f}/5 ({label})")

    sent = rec.get("sentiment_score")
    if sent is not None and not pd.isna(sent):
        if sent >= 70:
            fund_items.append("최근 뉴스 긍정 우세")
        elif sent <= 30:
            fund_items.append("최근 뉴스 부정 우세 — 주의")

    if horizon == "long":
        ordered = fund_items + tech_items
    else:
        ordered = tech_items + fund_items
    return ordered[:3] if ordered else ["종합 점수 상위 종목"]


def _attach_reasons(df: pd.DataFrame, horizon: str, commentary: dict | None = None) -> list[dict]:
    records = df.to_dict("records")
    commentary = commentary or {}
    for rec in records:
        rec["reasons"] = _make_reasons(rec, horizon)
        rec["ai_comment"] = commentary.get((rec.get("ticker"), horizon))
    return records


COUNTRY_LABELS = {"KR": "한국", "US": "미국", "JP": "일본"}

SECTION_META = [
    {"key": "short", "title": "단기 추천", "subtitle": "수 일 ~ 수 주", "color": "#d32f2f", "head_bg": "#faf5f5"},
    {"key": "long", "title": "장기 추천", "subtitle": "2~3년", "color": "#2e7d32", "head_bg": "#f4faf4"},
]


def _build_sections(picks: dict, commentary: dict | None = None) -> list[dict]:
    """Convert grouped picks into template-ready sections with country sub-groups."""
    sections = []
    for meta in SECTION_META:
        key = meta["key"]
        groups = []
        for country, df in picks.get(key, {}).items():
            records = _attach_reasons(df, key, commentary)
            if records:
                groups.append(
                    {
                        "country": country,
                        "label": COUNTRY_LABELS.get(country, country),
                        "records": records,
                    }
                )
        sections.append({**meta, "groups": groups})
    return sections


def _build_methodology(scoring_config: dict) -> dict:
    """Score calculation details shown in the report."""
    tech = scoring_config.get("technical", {})
    fund = scoring_config.get("fundamental", {})
    comp = scoring_config.get("composite", {})
    return {
        "tech_ratio_pct": round(comp.get("technical_ratio", 0.4) * 100),
        "fund_ratio_pct": round(comp.get("fundamental_ratio", 0.6) * 100),
        "rsi_w": tech.get("rsi_weight", 30),
        "macd_w": tech.get("macd_weight", 25),
        "ma_w": tech.get("ma_weight", 20),
        "bb_w": tech.get("bollinger_weight", 15),
        "vol_w": tech.get("volume_weight", 10),
        "ib_w": fund.get("ib_opinion_weight", 40),
        "gap_w": fund.get("target_price_gap_weight", 30),
        "news_w": fund.get("news_sentiment_weight", 20),
        "sector_w": fund.get("sector_momentum_weight", 10),
    }


def build_text_report(picks: dict, universe_notes: list[str] | None = None, commentary: dict | None = None) -> str:
    """Plain-text fallback version of the report (for mail clients without HTML)."""
    lines = [f"일일 종목 분석 리포트 ({datetime.today().strftime('%Y-%m-%d')})", ""]
    if universe_notes:
        lines.append("[분석 대상]")
        lines.extend(f"- {n}" for n in universe_notes)
        lines.append("")

    for meta in SECTION_META:
        lines.append(f"[{meta['title']} ({meta['subtitle']})]")
        for country, df in picks.get(meta["key"], {}).items():
            records = _attach_reasons(df, meta["key"], commentary)
            if not records:
                continue
            lines.append(f"  <{COUNTRY_LABELS.get(country, country)}>")
            for i, rec in enumerate(records, 1):
                lines.append(
                    f"  {i}. {rec.get('name')} ({rec.get('ticker')}) "
                    f"- 종합 {rec.get('composite_score')}점, 종가 {_fmt_price(rec.get('close'), rec.get('country'))}, "
                    f"20일 {_fmt_pct(rec.get('ret_20d'))}"
                )
                if rec.get("reasons"):
                    lines.append(f"     사유: {' / '.join(rec['reasons'])}")
                if rec.get("ai_comment"):
                    lines.append(f"     AI 해설: {rec['ai_comment']}")
        lines.append("")

    lines.append("본 리포트는 투자 권유가 아닌 정보 제공용입니다.")
    return "\n".join(lines)


def build_report(
    composite_df: pd.DataFrame,
    picks: dict,
    scoring_config: dict,
    universe_notes: list[str] | None = None,
    commentary: dict | None = None,
    ai_model_label: str | None = None,
) -> str:
    """Render the morning brief HTML."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["fmt_price"] = _fmt_price
    env.globals["fmt_pct"] = _fmt_pct
    env.globals["fmt_num"] = _fmt_num

    counts = composite_df["country"].value_counts().to_dict() if not composite_df.empty else {}

    template = env.get_template("report.html")
    html = template.render(
        report_date=datetime.today().strftime("%Y-%m-%d"),
        counts=counts,
        total_count=sum(counts.values()),
        universe_notes=universe_notes or [],
        ai_model_label=ai_model_label,
        method=_build_methodology(scoring_config),
        sections=_build_sections(picks, commentary),
        markets=picks.get("markets", pd.DataFrame()).to_dict("records"),
    )
    logger.info("Report HTML built (%d bytes)", len(html))
    return html


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    comp = pd.DataFrame(
        {
            "ticker": ["005930", "AAPL"],
            "country": ["KR", "US"],
            "name": ["삼성전자", "Apple"],
            "close": [70000, 180.5],
            "ret_5d": [1.2, -0.5],
            "ret_20d": [3.4, 2.1],
            "ret_60d": [8.0, 5.5],
            "rsi14": [58.0, 62.0],
            "vol_ratio": [1.8, 1.1],
            "target_gap_pct": [15.0, 8.0],
            "consensus_score": [4.1, 4.3],
            "technical_score": [70.0, 65.0],
            "fundamental_score": [75.0, 70.0],
            "composite_score": [73.0, 68.0],
        }
    )
    comp["short_term_score"] = [72.0, 66.0]
    comp["long_term_score"] = [68.0, 63.0]
    picks = {
        "short": {"KR": comp.iloc[[0]], "US": comp.iloc[[1]]},
        "long": {"KR": comp.iloc[[0]], "US": comp.iloc[[1]]},
        "markets": pd.DataFrame(
            [{"country": "KR", "count": 1, "avg_composite": 73.0, "avg_ret_20d": 3.4}]
        ),
    }
    html = build_report(comp, picks, {})
    print(html[:500])
