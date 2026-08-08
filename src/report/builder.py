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


def build_report(composite_df: pd.DataFrame, picks: dict, scoring_config: dict) -> str:
    """Render the morning brief HTML."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["fmt_price"] = _fmt_price
    env.globals["fmt_pct"] = _fmt_pct
    env.globals["fmt_num"] = _fmt_num

    comp_cfg = scoring_config.get("composite", {})
    counts = composite_df["country"].value_counts().to_dict() if not composite_df.empty else {}

    template = env.get_template("report.html")
    html = template.render(
        report_date=datetime.today().strftime("%Y-%m-%d"),
        counts=counts,
        tech_ratio=comp_cfg.get("technical_ratio", 0.4),
        fund_ratio=comp_cfg.get("fundamental_ratio", 0.6),
        short_term=picks.get("short_term", pd.DataFrame()).to_dict("records"),
        long_term=picks.get("long_term", pd.DataFrame()).to_dict("records"),
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
    picks = {
        "short_term": comp,
        "long_term": comp,
        "markets": pd.DataFrame(
            [{"country": "KR", "count": 1, "avg_composite": 73.0, "avg_ret_20d": 3.4}]
        ),
    }
    html = build_report(comp, picks, {})
    print(html[:500])
