"""Sector-specific metrics for banks/financials and REITs.

Standard EBITDA/FCF metrics mislead for these sectors, so we compute the
sector's own vocabulary. Some are approximations (labeled as such in the UI):
NIM uses total assets instead of earning assets; AFFO uses total capex instead
of maintenance capex.
"""
from __future__ import annotations

from .data import latest, yoy, safe_div


def sector_specific(snap: dict, ctype: str) -> dict:
    if ctype == "Bank or Financial Company":
        return _bank_metrics(snap)
    if ctype == "REIT":
        return _reit_metrics(snap)
    return {}


def _bank_metrics(snap):
    s, m = snap["series"], snap["metrics"]
    nii = latest(s.get("net_interest_income"))
    assets = latest(s.get("total_assets"))
    tb = latest(s.get("tangible_book"))
    sgna = latest(s.get("sgna"))
    rev = latest(s.get("revenue"))
    out = {
        "kind": "bank",
        "net_interest_income": nii,
        "nii_growth": yoy(s.get("net_interest_income")),
        "nim_proxy": safe_div(nii, assets),
        "p_tangible_book": safe_div(m.get("market_cap"), tb) if tb and tb > 0 else None,
        "tangible_book": tb,
        "efficiency_ratio": safe_div(sgna, rev),
        "notes": [
            "NIM approximated as net interest income / total assets (earning-asset "
            "detail is not available from this source).",
            "Efficiency ratio approximated from SG&A / revenue.",
            "Deposits, loan growth and charge-off detail are not available from "
            "Yahoo Finance; credit quality must be checked in the 10-K/10-Q.",
        ],
    }
    return {k: v for k, v in out.items() if v is not None} | {"kind": "bank", "notes": out["notes"]}


def _reit_metrics(snap):
    s, m = snap["series"], snap["metrics"]
    ni = latest(s.get("net_income"))
    dna = latest(s.get("dna"))
    capex = latest(s.get("capex"))          # negative in source data
    div_paid = latest(s.get("dividends_paid"))  # negative in source data
    shares = m.get("shares_outstanding")
    ffo = (ni + dna) if (ni is not None and dna is not None) else None
    affo = (ffo + capex) if (ffo is not None and capex is not None) else None
    out = {
        "kind": "reit",
        "ffo": ffo,
        "ffo_growth": _ffo_growth(s),
        "affo_approx": affo,
        "ffo_per_share": safe_div(ffo, shares),
        "p_ffo": safe_div(m.get("market_cap"), ffo) if ffo and ffo > 0 else None,
        "ffo_payout": safe_div(-div_paid, ffo) if (div_paid is not None and ffo and ffo > 0) else None,
        "notes": [
            "FFO computed as net income + depreciation & amortization (NAREIT "
            "adjustments for gains on sale are not available from this source).",
            "AFFO approximated with total capex, which overstates maintenance capex "
            "for REITs that are actively developing.",
            "Occupancy, same-store NOI and cap-rate data are not available from "
            "Yahoo Finance; check the supplemental filing.",
        ],
    }
    return {k: v for k, v in out.items() if v is not None} | {"kind": "reit", "notes": out["notes"]}


def _ffo_growth(s):
    ni, dna = s.get("net_income"), s.get("dna")
    if not ni or not dna or len(ni) < 2 or len(dna) < 2:
        return None
    dna_by_date = {d["date"]: d["value"] for d in dna}
    ffo_series = [{"date": d["date"], "value": d["value"] + dna_by_date[d["date"]]}
                  for d in ni if d["date"] in dna_by_date]
    return yoy(ffo_series)


def snapshot_rows(ss: dict) -> list:
    """Extra rows for the financial snapshot card."""
    from .narrative import fmt_usd, fmt_pct, fmt_x
    if not ss:
        return []
    if ss.get("kind") == "bank":
        return [
            {"label": "Net interest income", "value": fmt_usd(ss.get("net_interest_income"))},
            {"label": "NII growth (1y)", "value": fmt_pct(ss.get("nii_growth"))},
            {"label": "Net interest margin (approx.)", "value": fmt_pct(ss.get("nim_proxy"))},
            {"label": "Price / tangible book", "value": fmt_x(ss.get("p_tangible_book"))},
            {"label": "Efficiency ratio (approx.)", "value": fmt_pct(ss.get("efficiency_ratio"))},
        ]
    if ss.get("kind") == "reit":
        return [
            {"label": "FFO (NI + D&A)", "value": fmt_usd(ss.get("ffo"))},
            {"label": "FFO growth (1y)", "value": fmt_pct(ss.get("ffo_growth"))},
            {"label": "AFFO (approx.)", "value": fmt_usd(ss.get("affo_approx"))},
            {"label": "Price / FFO", "value": fmt_x(ss.get("p_ffo"))},
            {"label": "Dividend payout / FFO", "value": fmt_pct(ss.get("ffo_payout"))},
        ]
    return []
