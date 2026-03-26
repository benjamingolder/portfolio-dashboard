"""PDF report generator using fpdf2 + Matplotlib.

Pure Python, no system dependencies (no WeasyPrint/Cairo/Pango needed).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fpdf import FPDF

from app.models.portfolio import ClientPortfolio

logger = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
ACCENT   = (79,  140, 255)
GREEN    = (22,  163, 74)
RED      = (220, 38,  38)
DARK     = (15,  23,  42)
MUTED    = (100, 116, 139)
LIGHT_BG = (248, 250, 252)
BORDER   = (226, 232, 240)
WHITE    = (255, 255, 255)

CHART_COLORS = [
    "#4f8cff","#22c55e","#ef4444","#eab308","#a855f7",
    "#06b6d4","#f97316","#ec4899","#14b8a6","#8b5cf6",
    "#f59e0b","#3b82f6","#10b981","#f43f5e","#6366f1",
]

# ── Formatters ────────────────────────────────────────────────────────────────

_UNICODE_REPLACEMENTS = {
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2026": "...",
}

def _s(text: str) -> str:
    """Sanitize text: replace chars outside Latin-1 range (>255) for fpdf2 built-in fonts."""
    result = []
    for ch in str(text):
        if ord(ch) <= 255:
            result.append(ch)
        else:
            result.append(_UNICODE_REPLACEMENTS.get(ch, "?"))
    return "".join(result)


class SafeFPDF(FPDF):
    """FPDF subclass that auto-sanitizes all text passed to cell/multi_cell."""
    def cell(self, w=0, h=0, txt="", border=0, ln=0, align="", fill=False, link="", **kw):
        return super().cell(w, h, _s(txt), border=border, ln=ln, align=align, fill=fill, link=link, **kw)

    def multi_cell(self, w, h, txt="", border=0, align="J", fill=False, **kw):
        return super().multi_cell(w, h, _s(txt), border=border, align=align, fill=fill, **kw)


def _chf(n: float, d: int = 2) -> str:
    parts = f"{abs(n):,.{d}f}".split(".")
    parts[0] = parts[0].replace(",", "'")
    result = ".".join(parts)
    return f"-{result}" if n < 0 else result


def _pct(n: float, d: int = 1) -> str:
    return f"{'+' if n > 0 else ''}{n:.{d}f}%"


# ── Chart generators → PNG bytes ──────────────────────────────────────────────

def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    data = buf.read()
    plt.close(fig)
    return data


def _pie_chart(labels, values, colors) -> bytes | None:
    pairs = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not pairs:
        return None
    lbl, val, col = zip(*pairs)
    fig, ax = plt.subplots(figsize=(6, 3.5), facecolor="white")
    wedges, _, autotexts = ax.pie(
        val, colors=col,
        autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
        startangle=90, pctdistance=0.78,
    )
    for at in autotexts:
        at.set_fontsize(7); at.set_color("white"); at.set_weight("bold")
    ax.legend(wedges, [l[:26] for l in lbl],
              loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8, frameon=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _line_chart(dates, values, currency) -> bytes | None:
    if not dates or not values:
        return None
    fig, ax = plt.subplots(figsize=(10, 3.0), facecolor="white")
    ax.plot(range(len(dates)), values, color="#4f8cff", linewidth=1.5)
    ax.fill_between(range(len(dates)), values, alpha=0.08, color="#4f8cff")
    n = len(dates)
    step = max(1, n // 12)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][:7] for i in ticks], rotation=30, ha="right", fontsize=7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "'")))
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylabel(currency, fontsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.grid(axis="y", alpha=0.25, color="#cbd5e1")
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _bar_chart_years(years, amounts) -> bytes | None:
    if not years:
        return None
    fig, ax = plt.subplots(figsize=(7, 2.8), facecolor="white")
    ax.bar(range(len(years)), amounts, color="#22c55e", alpha=0.85)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([str(y) for y in years], fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "'")))
    ax.tick_params(axis="y", labelsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.grid(axis="y", alpha=0.25, color="#cbd5e1")
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _hbar_chart(labels, values, invested) -> bytes | None:
    n = min(len(labels), 15)
    if not n:
        return None
    lbl, val, inv = labels[:n], values[:n], invested[:n]
    fig, ax = plt.subplots(figsize=(10, max(3, n * 0.42)), facecolor="white")
    y = range(n)
    ax.barh([i + 0.22 for i in y], val, 0.4, label="Aktuell", color="#4f8cff", alpha=0.85)
    ax.barh([i - 0.22 for i in y], inv, 0.4, label="Investiert", color="#94a3b8", alpha=0.75)
    ax.set_yticks(list(y))
    ax.set_yticklabels([l[:30] for l in lbl], fontsize=8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "'")))
    ax.tick_params(axis="x", labelsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", alpha=0.25, color="#cbd5e1")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── fpdf2 layout helpers ──────────────────────────────────────────────────────

W = 174   # content width mm (A4 210 - 2*18 margins)
LM = 18   # left margin


def _header(pdf: FPDF, title: str, subtitle: str, date_str: str, logo_path: Path | None):
    """Draw page header with blue rule and optional logo."""
    # Logo top-right
    if logo_path and logo_path.exists():
        try:
            pdf.image(str(logo_path), x=LM + W - 40, y=pdf.get_y(), w=40, h=14, keep_aspect_ratio=True)
        except Exception:
            pass

    pdf.set_text_color(*DARK)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, title, ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, subtitle, ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 4, f"Berichtsdatum: {date_str}", ln=True)
    pdf.ln(1)
    # Blue rule
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.5)
    pdf.line(LM, pdf.get_y(), LM + W, pdf.get_y())
    pdf.ln(4)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _section(pdf: FPDF, title: str):
    """Draw a section title with blue left border."""
    y = pdf.get_y()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(LM, y, 2, 5, style="F")
    pdf.set_xy(LM + 4, y)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 5, title, ln=True)
    pdf.ln(2)


def _stat_box(pdf: FPDF, x: float, y: float, w: float, label: str, value: str,
              sub: str = "", sub_color: tuple = MUTED):
    """Draw a single KPI stat box."""
    h = 16
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_draw_color(*BORDER)
    pdf.rect(x, y, w, h, style="FD")
    # Label
    pdf.set_xy(x + 2, y + 2)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(*MUTED)
    pdf.cell(w - 4, 3, label.upper(), ln=True)
    # Value
    pdf.set_xy(x + 2, y + 5.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*DARK)
    # Truncate value if too long
    while pdf.get_string_width(value) > w - 4 and len(value) > 4:
        value = value[:-1]
    pdf.cell(w - 4, 5, value, ln=True)
    # Sub
    if sub:
        pdf.set_xy(x + 2, y + 11)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*sub_color)
        pdf.cell(w - 4, 3, sub, ln=True)


def _stats_grid(pdf: FPDF, items: list[dict]):
    """Draw a 3-column grid of stat boxes."""
    bw = (W - 4) / 3  # box width
    for i, item in enumerate(items):
        col = i % 3
        if col == 0 and i > 0:
            pdf.ln(18)
        x = LM + col * (bw + 2)
        y = pdf.get_y()
        sub_color = GREEN if item.get("positive") else RED if item.get("negative") else MUTED
        _stat_box(pdf, x, y, bw, item["label"], item["value"],
                  item.get("sub", ""), sub_color)
    pdf.ln(20)


def _embed_chart(pdf: FPDF, img_bytes: bytes, w: float = W, label: str = ""):
    """Embed a matplotlib PNG chart."""
    if label:
        _section(pdf, label)
    pdf.image(io.BytesIO(img_bytes), x=LM, w=w)
    pdf.ln(3)


def _table_header(pdf: FPDF, headers: list[str], widths: list[float], aligns: list[str]):
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_draw_color(*BORDER)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*MUTED)
    for h, w, a in zip(headers, widths, aligns):
        pdf.cell(w, 5, h.upper(), border="B", align=a, fill=True)
    pdf.ln()


def _table_row(pdf: FPDF, cells: list[str], widths: list[float], aligns: list[str],
               colors: list[tuple] | None = None):
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_draw_color(*BORDER)
    for i, (cell, w, a) in enumerate(zip(cells, widths, aligns)):
        color = colors[i] if colors and i < len(colors) else DARK
        pdf.set_text_color(*color)
        # Truncate if needed
        while pdf.get_string_width(cell) > w - 1 and len(cell) > 3:
            cell = cell[:-1]
        pdf.cell(w, 4.5, cell, border="B", align=a)
    pdf.ln()


def _heatmap_color(v: float) -> tuple[int, int, int]:
    if v > 5:   return (22, 163, 74)
    if v > 2:   return (74, 197, 130)
    if v > 0:   return (187, 237, 206)
    if v > -2:  return (252, 194, 194)
    if v > -5:  return (237, 100, 100)
    return (220, 38, 38)


def _draw_heatmap(pdf: FPDF, monthly_by_year: dict, years: list):
    """Draw the monthly returns heatmap as colored cells."""
    MONTHS = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"]
    yr_w = 10
    cell_w = (W - yr_w) / 12
    cell_h = 5

    pdf.set_font("Helvetica", "B", 6)
    pdf.set_text_color(*MUTED)
    pdf.set_fill_color(*LIGHT_BG)
    # Header row
    pdf.cell(yr_w, cell_h, "", border=0, fill=True)
    for m in MONTHS:
        pdf.cell(cell_w, cell_h, m, border=0, align="C", fill=True)
    pdf.ln()

    for year in years:
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*MUTED)
        pdf.set_fill_color(*LIGHT_BG)
        pdf.cell(yr_w, cell_h, str(year), border=0, align="R", fill=True)
        month_data = monthly_by_year.get(year, {})
        for m in range(1, 13):
            v = month_data.get(m)
            if v is not None:
                r, g, b = _heatmap_color(v)
                pdf.set_fill_color(r, g, b)
                text_color = WHITE if abs(v) > 2 else DARK
                pdf.set_text_color(*text_color)
                pdf.set_font("Helvetica", "", 6)
                pdf.cell(cell_w, cell_h, f"{'+' if v > 0 else ''}{v:.1f}", border=0, align="C", fill=True)
            else:
                pdf.set_fill_color(*LIGHT_BG)
                pdf.cell(cell_w, cell_h, "", border=0, fill=True)
        pdf.ln()
    pdf.ln(3)


# ── Main PDF generation ───────────────────────────────────────────────────────

def generate_client_pdf(client: ClientPortfolio, logo_path: Path | None = None) -> bytes:
    """Generate a multi-page A4 PDF report for a single client."""
    from datetime import date
    date_str = date.today().strftime("%d.%m.%Y")
    p = client.performance

    # ── Pre-generate charts ──
    alloc_bytes = None
    if client.asset_allocation:
        alloc_bytes = _pie_chart(
            [a.name for a in client.asset_allocation],
            [a.value for a in client.asset_allocation],
            [a.color or CHART_COLORS[i % len(CHART_COLORS)] for i, a in enumerate(client.asset_allocation)],
        )

    history_bytes = None
    if client.value_history:
        history_bytes = _line_chart(
            [v.date for v in client.value_history],
            [v.value for v in client.value_history],
            client.base_currency,
        )

    holdings_bytes = None
    if client.holdings:
        holdings_bytes = _hbar_chart(
            [h.security.name for h in client.holdings],
            [h.current_value for h in client.holdings],
            [h.invested for h in client.holdings],
        )

    div_year_bytes = None
    by_year_items: list[tuple] = []
    by_security_items: list[tuple] = []
    if client.dividends_total > 0 and client.dividends:
        by_year_raw = sorted((int(k), float(v)) for k, v in client.dividends.by_year.items())
        if by_year_raw:
            years_list, amounts_list = zip(*by_year_raw)
            div_year_bytes = _bar_chart_years(list(years_list), list(amounts_list))
            by_year_items = list(reversed(by_year_raw))
        by_security_items = sorted(
            ((name, float(amt)) for name, amt in client.dividends.by_security.items()),
            key=lambda x: x[1], reverse=True
        )[:12]

    # Monthly heatmap data
    monthly_by_year: dict[int, dict[int, float]] = {}
    for mr in client.monthly_returns:
        monthly_by_year.setdefault(int(mr.year), {})[int(mr.month)] = float(mr.return_pct)
    heatmap_years = sorted(monthly_by_year.keys(), reverse=True)[:5]

    # ── Setup PDF ──
    pdf = SafeFPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(LM, 15, LM)
    pdf.set_auto_page_break(True, margin=15)

    # ════════════════════════════════════════
    # PAGE 1: SUMMARY
    # ════════════════════════════════════════
    pdf.add_page()
    _header(pdf, client.client_name,
            f"Vermögensübersicht · {client.base_currency}", date_str, logo_path)

    _section(pdf, "Kennzahlen im Überblick")
    gain_sub = f"{_pct(client.gain_loss_pct)} ({_chf(client.gain_loss)} {client.base_currency})"
    _stats_grid(pdf, [
        {"label": "Gesamtvermögen",    "value": f"{_chf(client.total_value)} {client.base_currency}",
         "sub": gain_sub, "positive": client.gain_loss >= 0, "negative": client.gain_loss < 0},
        {"label": "Investiert",        "value": f"{_chf(client.total_invested)} {client.base_currency}"},
        {"label": "Gewinn / Verlust",  "value": f"{_chf(client.gain_loss)} {client.base_currency}",
         "positive": client.gain_loss >= 0, "negative": client.gain_loss < 0},
        {"label": "Rendite p.a.",      "value": _pct(p.annual_return),
         "positive": p.annual_return >= 0, "negative": p.annual_return < 0},
        {"label": "TTWROR",            "value": _pct(p.ttwror),
         "positive": p.ttwror >= 0, "negative": p.ttwror < 0},
        {"label": "YTD",               "value": _pct(p.ytd_return),
         "positive": p.ytd_return >= 0, "negative": p.ytd_return < 0},
        {"label": "Volatilität",       "value": f"{p.volatility:.1f}%"},
        {"label": "Sharpe Ratio",      "value": f"{p.sharpe_ratio:.2f}"},
        {"label": "Max. Drawdown",     "value": f"-{p.max_drawdown:.1f}%", "negative": True},
    ])

    if client.dividends_total > 0:
        div_yield = client.dividends_total / client.total_invested * 100 if client.total_invested else 0
        _stats_grid(pdf, [
            {"label": "Dividenden Total",    "value": f"{_chf(client.dividends_total)} {client.base_currency}", "positive": True},
            {"label": "Dividendenrendite",   "value": _pct(div_yield, 2), "positive": True},
            {"label": "Dividendenquellen",   "value": str(len(client.dividends.by_security) if client.dividends else 0)},
        ])

    if alloc_bytes:
        _section(pdf, "Asset Allocation")
        # Chart left, table right
        chart_w = W * 0.52
        table_w = W * 0.44
        y_before = pdf.get_y()
        pdf.image(io.BytesIO(alloc_bytes), x=LM, y=y_before, w=chart_w)
        chart_h = chart_w * (3.5 / 6)  # approximate aspect ratio
        # Table on right
        tx = LM + chart_w + 4
        pdf.set_xy(tx, y_before)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*MUTED)
        pdf.set_fill_color(*LIGHT_BG)
        for hdr, hw, ha in zip(["Kategorie", "Wert", "Anteil"],
                                [table_w * 0.5, table_w * 0.3, table_w * 0.2], ["L", "R", "R"]):
            pdf.cell(hw, 4.5, hdr.upper(), border="B", align=ha, fill=True)
        pdf.ln()
        for a in client.asset_allocation:
            pdf.set_xy(tx, pdf.get_y())
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*DARK)
            name = a.name[:22]
            pdf.cell(table_w * 0.5, 4, name, border="B")
            pdf.set_text_color(*DARK)
            pdf.cell(table_w * 0.3, 4, _chf(a.value), border="B", align="R")
            pdf.cell(table_w * 0.2, 4, f"{a.percentage:.1f}%", border="B", align="R")
            pdf.ln()
        pdf.set_y(y_before + max(chart_h, pdf.get_y() - y_before) + 3)

    # ════════════════════════════════════════
    # PAGE 2: PERFORMANCE
    # ════════════════════════════════════════
    pdf.add_page()
    _header(pdf, "Performance", client.client_name, date_str, logo_path)

    if history_bytes:
        _embed_chart(pdf, history_bytes, W, "Portfoliowert-Entwicklung")

    _section(pdf, "Renditen im Vergleich")
    _stats_grid(pdf, [
        {"label": "YTD",       "value": _pct(p.ytd_return),    "positive": p.ytd_return >= 0,  "negative": p.ytd_return < 0},
        {"label": "1 Jahr",    "value": _pct(p.return_1y),     "positive": p.return_1y >= 0,   "negative": p.return_1y < 0},
        {"label": "3 Jahre",   "value": _pct(p.return_3y),     "positive": p.return_3y >= 0,   "negative": p.return_3y < 0},
        {"label": "5 Jahre",   "value": _pct(p.return_5y),     "positive": p.return_5y >= 0,   "negative": p.return_5y < 0},
        {"label": "Rendite p.a.", "value": _pct(p.annual_return), "positive": p.annual_return >= 0, "negative": p.annual_return < 0},
        {"label": "Volatilität",  "value": f"{p.volatility:.1f}%"},
    ])

    if heatmap_years:
        _section(pdf, "Monatliche Renditen")
        _draw_heatmap(pdf, monthly_by_year, heatmap_years)

    # ════════════════════════════════════════
    # PAGE 3: POSITIONS
    # ════════════════════════════════════════
    pdf.add_page()
    _header(pdf, "Positionen", client.client_name, date_str, logo_path)

    if holdings_bytes:
        _embed_chart(pdf, holdings_bytes, W, "Wert vs. Investiert")

    _section(pdf, f"Alle Positionen ({len(client.holdings)})")
    col_w = [W*0.28, W*0.14, W*0.14, W*0.1, W*0.12, W*0.12, W*0.1]
    _table_header(pdf, ["Wertpapier", "ISIN", "Kategorie", "Anteile", "Wert", "Investiert", "G/V %"],
                  col_w, ["L","L","L","R","R","R","R"])
    for h in client.holdings:
        gv_color = GREEN if h.gain_loss_pct >= 0 else RED
        _table_row(pdf,
            [h.security.name, h.security.isin or "", h.category,
             _chf(h.shares, 4), _chf(h.current_value), _chf(h.invested), _pct(h.gain_loss_pct)],
            col_w, ["L","L","L","R","R","R","R"],
            [DARK, MUTED, MUTED, DARK, DARK, DARK, gv_color])

    # Total row
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_text_color(*DARK)
    total_color = GREEN if client.gain_loss >= 0 else RED
    for cell, w, a, color in [
        ("Total", col_w[0]+col_w[1]+col_w[2]+col_w[3], "L", DARK),
        (_chf(client.total_value), col_w[4], "R", DARK),
        (_chf(client.total_invested), col_w[5], "R", DARK),
        (_pct(client.gain_loss_pct), col_w[6], "R", total_color),
    ]:
        pdf.set_text_color(*color)
        pdf.cell(w, 5, cell, border="T", align=a, fill=True)
    pdf.ln(8)

    # Cash accounts
    cash = [a for a in client.accounts if a.balance > 0]
    if cash:
        _section(pdf, "Cash-Bestände")
        _table_header(pdf, ["Konto", "Währung", "Saldo"], [W*0.6, W*0.2, W*0.2], ["L","L","R"])
        for a in cash:
            _table_row(pdf, [a.name, a.currency, _chf(a.balance)],
                       [W*0.6, W*0.2, W*0.2], ["L","L","R"])

    # ════════════════════════════════════════
    # PAGE 4: DIVIDENDS (if any)
    # ════════════════════════════════════════
    if client.dividends_total > 0:
        pdf.add_page()
        _header(pdf, "Dividenden", client.client_name, date_str, logo_path)

        div_yield = client.dividends_total / client.total_invested * 100 if client.total_invested else 0
        _section(pdf, "Dividenden-Übersicht")
        _stats_grid(pdf, [
            {"label": "Dividenden Total",  "value": f"{_chf(client.dividends_total)} {client.base_currency}", "positive": True},
            {"label": "Dividendenrendite", "value": _pct(div_yield, 2), "positive": True},
            {"label": "Quellen",           "value": str(len(client.dividends.by_security) if client.dividends else 0)},
        ])

        if div_year_bytes:
            _embed_chart(pdf, div_year_bytes, W * 0.6, "Dividenden pro Jahr")

        if by_year_items or by_security_items:
            _section(pdf, "Detailübersicht")
            half = W / 2 - 3
            y0 = pdf.get_y()
            # Left: by year
            if by_year_items:
                pdf.set_xy(LM, y0)
                _table_header(pdf, ["Jahr", f"Betrag ({client.base_currency})"],
                              [half * 0.45, half * 0.55], ["L", "R"])
                for year, amt in by_year_items:
                    pdf.set_xy(LM, pdf.get_y())
                    _table_row(pdf, [str(year), _chf(float(amt))],
                               [half * 0.45, half * 0.55], ["L", "R"],
                               [DARK, GREEN])
            # Right: by security
            if by_security_items:
                rx = LM + half + 6
                pdf.set_xy(rx, y0)
                _table_header(pdf, ["Wertpapier", f"Total ({client.base_currency})"],
                              [half * 0.65, half * 0.35], ["L", "R"])
                for name, amt in by_security_items:
                    pdf.set_xy(rx, pdf.get_y())
                    _table_row(pdf, [name[:28], _chf(float(amt))],
                               [half * 0.65, half * 0.35], ["L", "R"],
                               [DARK, GREEN])

    # ── Footer on last page ──
    pdf.set_y(-18)
    pdf.set_draw_color(*BORDER)
    pdf.line(LM, pdf.get_y(), LM + W, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 6.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(W / 2, 4, f"{client.client_name} - Vertraulich - Nur fuer den Empfaenger")
    pdf.cell(W / 2, 4, f"Erstellt am {date_str}", align="R")

    return bytes(pdf.output())
