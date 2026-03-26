"""PDF report generator for portfolio clients.

Uses WeasyPrint (HTML→PDF) and Matplotlib (server-side charts as embedded PNG).
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from jinja2 import Environment, BaseLoader

from app.models.portfolio import ClientPortfolio

logger = logging.getLogger(__name__)

CHART_COLORS = [
    "#4f8cff", "#22c55e", "#ef4444", "#eab308", "#a855f7",
    "#06b6d4", "#f97316", "#ec4899", "#14b8a6", "#8b5cf6",
    "#f59e0b", "#3b82f6", "#10b981", "#f43f5e", "#6366f1",
]

# ── Formatting helpers ────────────────────────────────────────────────────────

def _chf(n: float, d: int = 2) -> str:
    """Format number with Swiss apostrophe thousands separator."""
    parts = f"{abs(n):,.{d}f}".split(".")
    parts[0] = parts[0].replace(",", "'")
    result = ".".join(parts)
    return f"-{result}" if n < 0 else result


def _pct(n: float, d: int = 1) -> str:
    return f"{'+' if n > 0 else ''}{n:.{d}f}%"


# ── Chart generators ──────────────────────────────────────────────────────────

def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{data}"


def _pie_chart(labels: list[str], values: list[float], colors: list[str]) -> str:
    pairs = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not pairs:
        return ""
    lbl, val, col = zip(*pairs)
    fig, ax = plt.subplots(figsize=(6, 3.8), facecolor="white")
    wedges, _, autotexts = ax.pie(
        val, colors=col,
        autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
        startangle=90, pctdistance=0.78,
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color("white")
        at.set_weight("bold")
    ax.legend(
        wedges, [l[:28] for l in lbl],
        loc="center left", bbox_to_anchor=(1, 0.5),
        fontsize=8, frameon=False,
    )
    fig.tight_layout()
    return _fig_to_b64(fig)


def _line_chart(dates: list[str], values: list[float], currency: str) -> str:
    if not dates or not values:
        return ""
    fig, ax = plt.subplots(figsize=(10, 3.2), facecolor="white")
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
    return _fig_to_b64(fig)


def _bar_chart_years(years: list, amounts: list[float]) -> str:
    if not years:
        return ""
    fig, ax = plt.subplots(figsize=(7, 3), facecolor="white")
    ax.bar(range(len(years)), amounts, color="#22c55e", alpha=0.85)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([str(y) for y in years], fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "'")))
    ax.tick_params(axis="y", labelsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.grid(axis="y", alpha=0.25, color="#cbd5e1")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _hbar_chart(labels: list[str], values: list[float], invested: list[float]) -> str:
    n = min(len(labels), 15)
    if not n:
        return ""
    lbl, val, inv = labels[:n], values[:n], invested[:n]
    fig, ax = plt.subplots(figsize=(10, max(3, n * 0.42)), facecolor="white")
    y = range(n)
    ax.barh([i + 0.22 for i in y], val, 0.4, label="Aktuell", color="#4f8cff", alpha=0.85)
    ax.barh([i - 0.22 for i in y], inv, 0.4, label="Investiert", color="#94a3b8", alpha=0.75)
    ax.set_yticks(list(y))
    ax.set_yticklabels([l[:32] for l in lbl], fontsize=8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "'")))
    ax.tick_params(axis="x", labelsize=8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", alpha=0.25, color="#cbd5e1")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    return _fig_to_b64(fig)


# ── Logo helper ───────────────────────────────────────────────────────────────

def _logo_src(logo_path: Path | None) -> str:
    if not logo_path or not logo_path.exists():
        return ""
    ext = logo_path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "svg": "svg+xml"}.get(ext, "png")
    data = base64.b64encode(logo_path.read_bytes()).decode()
    return f"data:image/{mime};base64,{data}"


# ── Heatmap color (matches JS logic) ─────────────────────────────────────────

def _heatmap_color(v: float) -> str:
    if v is None:
        return "transparent"
    if v > 5:   return "rgba(22,163,74,0.80)"
    if v > 2:   return "rgba(22,163,74,0.55)"
    if v > 0:   return "rgba(22,163,74,0.25)"
    if v > -2:  return "rgba(220,38,38,0.25)"
    if v > -5:  return "rgba(220,38,38,0.55)"
    return "rgba(220,38,38,0.80)"


# ── Jinja2 template ───────────────────────────────────────────────────────────

_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@page {
  size: A4;
  margin: 1.5cm 1.8cm 2cm 1.8cm;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #1e293b; line-height:1.4; }

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 2px solid #4f8cff;
  padding-bottom: 10px;
  margin-bottom: 18px;
}
.header-left h1 { font-size: 17pt; font-weight: 700; color: #0f172a; margin-bottom: 3px; }
.header-left .subtitle { font-size: 9pt; color: #64748b; }
.header-left .report-date { font-size: 8pt; color: #94a3b8; margin-top: 3px; }
.header-right img { max-height: 56px; max-width: 160px; object-fit: contain; }

.section { margin-bottom: 20px; }
.section-title {
  font-size: 10pt; font-weight: 600; color: #0f172a;
  border-left: 3px solid #4f8cff;
  padding-left: 8px;
  margin-bottom: 10px;
}

.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }
.stat-box {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 9px 11px;
}
.stat-box .lbl { font-size: 6.5pt; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 3px; }
.stat-box .val { font-size: 13pt; font-weight: 700; color: #0f172a; line-height:1.2; }
.stat-box .sub { font-size: 7.5pt; margin-top: 2px; }

.pos { color: #16a34a; }
.neg { color: #dc2626; }
.neu { color: #475569; }

table { width: 100%; border-collapse: collapse; font-size: 8pt; }
th {
  text-align: left; padding: 4px 7px;
  background: #f1f5f9; border-bottom: 1px solid #cbd5e1;
  font-size: 7pt; font-weight: 600; color: #475569;
  text-transform: uppercase; letter-spacing: 0.3px;
}
td { padding: 4px 7px; border-bottom: 1px solid #f1f5f9; }
tr:last-child td { border-bottom: none; }
.tr-total td { font-weight: 700; background: #f1f5f9; border-top: 1px solid #cbd5e1; }
.text-right { text-align: right; }
.mono { font-family: 'Courier New', monospace; }

.chart-img { width: 100%; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }

.page-break { page-break-before: always; }

.hm-table { border-collapse: collapse; font-size: 7pt; width: 100%; }
.hm-table th, .hm-table td { padding: 3px 2px; text-align: center; border: 1px solid #e2e8f0; min-width: 26px; }
.hm-table th { background: #f1f5f9; font-size: 6.5pt; }
.hm-table .yr { text-align: right; font-weight: 600; color: #64748b; padding-right: 6px; }

.footer {
  position: fixed; bottom: 0.5cm; left: 1.8cm; right: 1.8cm;
  font-size: 6.5pt; color: #94a3b8;
  display: flex; justify-content: space-between;
  border-top: 1px solid #e2e8f0; padding-top: 3px;
}
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
.confidential { font-size: 7pt; color: #94a3b8; text-align: center; margin-top: 10px; font-style: italic; }
</style>
</head>
<body>

<div class="footer">
  <span>{{ client_name }} &mdash; Vertraulich &mdash; Nur für den Empfänger</span>
  <span>Erstellt am {{ report_date }}</span>
</div>

{# ── PAGE 1: SUMMARY ── #}
<div class="report-header">
  <div class="header-left">
    <h1>{{ client_name }}</h1>
    <div class="subtitle">Vermögensübersicht &middot; {{ base_currency }}</div>
    <div class="report-date">Berichtsdatum: {{ report_date }}</div>
  </div>
  <div class="header-right">
    {% if logo_src %}<img src="{{ logo_src }}" alt="Logo">{% endif %}
  </div>
</div>

<div class="section">
  <div class="section-title">Kennzahlen im Überblick</div>
  <div class="stats-grid">
    <div class="stat-box">
      <div class="lbl">Gesamtvermögen</div>
      <div class="val">{{ total_value }} {{ base_currency }}</div>
      <div class="sub {{ 'pos' if gain_loss >= 0 else 'neg' }}">{{ gain_loss_pct }} ({{ gain_loss }} {{ base_currency }})</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Investiert</div>
      <div class="val">{{ total_invested }} {{ base_currency }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Gewinn / Verlust</div>
      <div class="val {{ 'pos' if gain_loss >= 0 else 'neg' }}">{{ gain_loss }} {{ base_currency }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Rendite p.a.</div>
      <div class="val {{ 'pos' if annual_return >= 0 else 'neg' }}">{{ annual_return_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">TTWROR (Gesamtrendite)</div>
      <div class="val {{ 'pos' if ttwror >= 0 else 'neg' }}">{{ ttwror_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">YTD</div>
      <div class="val {{ 'pos' if ytd >= 0 else 'neg' }}">{{ ytd_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Volatilität</div>
      <div class="val neu">{{ volatility_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Sharpe Ratio</div>
      <div class="val neu">{{ sharpe_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Max. Drawdown</div>
      <div class="val neg">{{ max_drawdown_fmt }}</div>
    </div>
  </div>
</div>

{% if alloc_chart %}
<div class="section">
  <div class="section-title">Asset Allocation</div>
  <div class="two-col">
    <img class="chart-img" src="{{ alloc_chart }}">
    <table>
      <thead><tr><th>Kategorie</th><th class="text-right">Wert ({{ base_currency }})</th><th class="text-right">Anteil</th></tr></thead>
      <tbody>
        {% for a in asset_allocation %}
        <tr>
          <td><span class="dot" style="background:{{ a.color }}"></span>{{ a.name }}</td>
          <td class="text-right mono">{{ a.value_fmt }}</td>
          <td class="text-right mono">{{ a.pct_fmt }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}

{% if dividends_total > 0 %}
<div class="stats-grid" style="margin-top:-8px">
  <div class="stat-box">
    <div class="lbl">Dividenden Total</div>
    <div class="val pos">{{ dividends_total_fmt }} {{ base_currency }}</div>
  </div>
  <div class="stat-box">
    <div class="lbl">Dividendenrendite</div>
    <div class="val pos">{{ dividend_yield_fmt }}</div>
  </div>
  <div class="stat-box">
    <div class="lbl">Dividendenquellen</div>
    <div class="val neu">{{ dividend_sources }}</div>
  </div>
</div>
{% endif %}


{# ── PAGE 2: PERFORMANCE ── #}
<div class="page-break"></div>

<div class="report-header">
  <div class="header-left">
    <h1>Performance</h1>
    <div class="subtitle">{{ client_name }}</div>
  </div>
  <div class="header-right">
    {% if logo_src %}<img src="{{ logo_src }}" alt="Logo">{% endif %}
  </div>
</div>

{% if value_history_chart %}
<div class="section">
  <div class="section-title">Portfoliowert-Entwicklung</div>
  <img class="chart-img" src="{{ value_history_chart }}">
</div>
{% endif %}

<div class="section">
  <div class="section-title">Renditen im Vergleich</div>
  <div class="stats-grid">
    <div class="stat-box"><div class="lbl">YTD</div><div class="val {{ 'pos' if ytd >= 0 else 'neg' }}">{{ ytd_fmt }}</div></div>
    <div class="stat-box"><div class="lbl">1 Jahr</div><div class="val {{ 'pos' if r1y >= 0 else 'neg' }}">{{ r1y_fmt }}</div></div>
    <div class="stat-box"><div class="lbl">3 Jahre p.a.</div><div class="val {{ 'pos' if r3y >= 0 else 'neg' }}">{{ r3y_fmt }}</div></div>
    <div class="stat-box"><div class="lbl">5 Jahre p.a.</div><div class="val {{ 'pos' if r5y >= 0 else 'neg' }}">{{ r5y_fmt }}</div></div>
    <div class="stat-box"><div class="lbl">Rendite p.a.</div><div class="val {{ 'pos' if annual_return >= 0 else 'neg' }}">{{ annual_return_fmt }}</div></div>
    <div class="stat-box"><div class="lbl">Volatilität</div><div class="val neu">{{ volatility_fmt }}</div></div>
  </div>
</div>

{% if monthly_by_year %}
<div class="section">
  <div class="section-title">Monatliche Renditen (Heatmap)</div>
  <table class="hm-table">
    <thead>
      <tr>
        <th style="text-align:right">Jahr</th>
        <th>Jan</th><th>Feb</th><th>Mär</th><th>Apr</th><th>Mai</th><th>Jun</th>
        <th>Jul</th><th>Aug</th><th>Sep</th><th>Okt</th><th>Nov</th><th>Dez</th>
      </tr>
    </thead>
    <tbody>
      {% for year in monthly_years %}
      <tr>
        <td class="yr">{{ year }}</td>
        {% for m in range(1, 13) %}
        {% set v = monthly_by_year[year].get(m) %}
        {% if v is not none %}
        <td style="background:{{ hmc(v) }};color:{% if v|abs > 2 %}#fff{% else %}#1e293b{% endif %}">{{ '+' if v > 0 else '' }}{{ '%.1f'|format(v) }}</td>
        {% else %}
        <td></td>
        {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}


{# ── PAGE 3: POSITIONS ── #}
<div class="page-break"></div>

<div class="report-header">
  <div class="header-left">
    <h1>Positionen</h1>
    <div class="subtitle">{{ client_name }}</div>
  </div>
  <div class="header-right">
    {% if logo_src %}<img src="{{ logo_src }}" alt="Logo">{% endif %}
  </div>
</div>

{% if holdings_chart %}
<div class="section">
  <div class="section-title">Wert vs. Investiert</div>
  <img class="chart-img" src="{{ holdings_chart }}">
</div>
{% endif %}

<div class="section">
  <div class="section-title">Alle Positionen ({{ holdings|length }})</div>
  <table>
    <thead>
      <tr>
        <th>Wertpapier</th>
        <th>ISIN</th>
        <th>Kategorie</th>
        <th class="text-right">Anteile</th>
        <th class="text-right">Wert ({{ base_currency }})</th>
        <th class="text-right">Investiert</th>
        <th class="text-right">G/V %</th>
      </tr>
    </thead>
    <tbody>
      {% for h in holdings %}
      <tr>
        <td>{{ h.name }}</td>
        <td style="color:#64748b;font-size:7pt">{{ h.isin or '—' }}</td>
        <td style="color:#64748b">{{ h.category }}</td>
        <td class="text-right mono">{{ h.shares }}</td>
        <td class="text-right mono">{{ h.value }}</td>
        <td class="text-right mono">{{ h.invested }}</td>
        <td class="text-right mono {{ 'pos' if h.gain_pct_raw >= 0 else 'neg' }}">{{ h.gain_pct }}</td>
      </tr>
      {% endfor %}
      <tr class="tr-total">
        <td colspan="4">Total</td>
        <td class="text-right mono">{{ total_value }} {{ base_currency }}</td>
        <td class="text-right mono">{{ total_invested }} {{ base_currency }}</td>
        <td class="text-right mono {{ 'pos' if gain_loss >= 0 else 'neg' }}">{{ gain_loss_pct }}</td>
      </tr>
    </tbody>
  </table>
</div>

{% if cash_accounts %}
<div class="section">
  <div class="section-title">Cash-Bestände</div>
  <table>
    <thead><tr><th>Konto</th><th>Währung</th><th class="text-right">Saldo</th></tr></thead>
    <tbody>
      {% for a in cash_accounts %}
      <tr><td>{{ a.name }}</td><td>{{ a.currency }}</td><td class="text-right mono">{{ a.balance_fmt }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}


{# ── PAGE 4: DIVIDENDS (only if relevant) ── #}
{% if dividends_total > 0 %}
<div class="page-break"></div>

<div class="report-header">
  <div class="header-left">
    <h1>Dividenden</h1>
    <div class="subtitle">{{ client_name }}</div>
  </div>
  <div class="header-right">
    {% if logo_src %}<img src="{{ logo_src }}" alt="Logo">{% endif %}
  </div>
</div>

<div class="section">
  <div class="section-title">Dividenden-Übersicht</div>
  <div class="stats-grid">
    <div class="stat-box">
      <div class="lbl">Dividenden Total</div>
      <div class="val pos">{{ dividends_total_fmt }} {{ base_currency }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Dividendenrendite</div>
      <div class="val pos">{{ dividend_yield_fmt }}</div>
    </div>
    <div class="stat-box">
      <div class="lbl">Anzahl Quellen</div>
      <div class="val neu">{{ dividend_sources }}</div>
    </div>
  </div>
</div>

{% if div_year_chart %}
<div class="section">
  <div class="section-title">Dividenden pro Jahr</div>
  <img class="chart-img" src="{{ div_year_chart }}">
</div>
{% endif %}

{% if div_by_year or div_by_security %}
<div class="section">
  <div class="section-title">Detailübersicht</div>
  <div class="two-col">
    {% if div_by_year %}
    <table>
      <thead><tr><th>Jahr</th><th class="text-right">Betrag ({{ base_currency }})</th></tr></thead>
      <tbody>
        {% for year, amt in div_by_year %}
        <tr><td>{{ year }}</td><td class="text-right mono pos">{{ amt }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
    {% if div_by_security %}
    <table>
      <thead><tr><th>Wertpapier</th><th class="text-right">Total ({{ base_currency }})</th></tr></thead>
      <tbody>
        {% for name, amt in div_by_security %}
        <tr>
          <td style="font-size:7.5pt">{{ name[:36] }}</td>
          <td class="text-right mono pos">{{ amt }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
</div>
{% endif %}
{% endif %}

<div class="confidential">
  Dieses Dokument enthält vertrauliche Finanzinformationen und ist ausschliesslich für den genannten Empfänger bestimmt.
</div>

</body>
</html>
"""


# ── Public API ────────────────────────────────────────────────────────────────

def generate_client_pdf(client: ClientPortfolio, logo_path: Path | None = None) -> bytes:
    """Generate a multi-page PDF report for a single client portfolio."""
    from weasyprint import HTML

    from datetime import date
    report_date = date.today().strftime("%d.%m.%Y")

    p = client.performance

    # --- Charts ---
    alloc_chart = ""
    if client.asset_allocation:
        alloc_chart = _pie_chart(
            [a.name for a in client.asset_allocation],
            [a.value for a in client.asset_allocation],
            [a.color or CHART_COLORS[i % len(CHART_COLORS)] for i, a in enumerate(client.asset_allocation)],
        )

    value_history_chart = ""
    if client.value_history:
        value_history_chart = _line_chart(
            [v.date for v in client.value_history],
            [v.value for v in client.value_history],
            client.base_currency,
        )

    holdings_chart = ""
    if client.holdings:
        holdings_chart = _hbar_chart(
            [h.security.name for h in client.holdings],
            [h.current_value for h in client.holdings],
            [h.invested for h in client.holdings],
        )

    div_year_chart = ""
    div_by_year: list[tuple] = []
    div_by_security: list[tuple] = []
    if client.dividends_total > 0 and client.dividends:
        sorted_years = sorted(client.dividends.by_year.items())
        if sorted_years:
            years, amounts = zip(*sorted_years)
            div_year_chart = _bar_chart_years(list(years), list(amounts))
            div_by_year = [(y, _chf(a)) for y, a in sorted(sorted_years, reverse=True)]
        div_by_security = sorted(
            [(name, _chf(amt)) for name, amt in client.dividends.by_security.items()],
            key=lambda x: float(x[1].replace("'", "").replace(",", ".")),
            reverse=True,
        )[:12]

    # Monthly returns heatmap data
    monthly_by_year: dict[int, dict[int, float]] = {}
    for mr in client.monthly_returns:
        monthly_by_year.setdefault(mr.year, {})[mr.month] = mr.return_pct
    monthly_years = sorted(monthly_by_year.keys(), reverse=True)[:5]  # last 5 years

    # Holdings table data
    holdings_rows = []
    for h in client.holdings:
        holdings_rows.append({
            "name": h.security.name,
            "isin": h.security.isin,
            "category": h.category,
            "shares": _chf(h.shares, 4),
            "value": _chf(h.current_value),
            "invested": _chf(h.invested),
            "gain_pct": _pct(h.gain_loss_pct),
            "gain_pct_raw": h.gain_loss_pct,
        })

    # Cash accounts
    cash_accounts = [
        {"name": a.name, "currency": a.currency, "balance_fmt": _chf(a.balance)}
        for a in client.accounts
        if a.balance > 0
    ]

    # Dividend yield
    dividend_yield = (client.dividends_total / client.total_invested * 100) if client.total_invested > 0 else 0

    env = Environment(loader=BaseLoader())
    env.globals["hmc"] = _heatmap_color
    template = env.from_string(_TEMPLATE)

    html_str = template.render(
        client_name=client.client_name,
        base_currency=client.base_currency,
        report_date=report_date,
        logo_src=_logo_src(logo_path),
        # Summary
        total_value=_chf(client.total_value),
        total_invested=_chf(client.total_invested),
        gain_loss=_chf(client.gain_loss),
        gain_loss_pct=_pct(client.gain_loss_pct),
        annual_return=p.annual_return,
        annual_return_fmt=_pct(p.annual_return),
        ttwror=p.ttwror,
        ttwror_fmt=_pct(p.ttwror),
        ytd=p.ytd_return,
        ytd_fmt=_pct(p.ytd_return),
        volatility_fmt=f"{p.volatility:.1f}%",
        sharpe_fmt=f"{p.sharpe_ratio:.2f}",
        max_drawdown_fmt=f"-{p.max_drawdown:.1f}%",
        r1y=p.return_1y,
        r1y_fmt=_pct(p.return_1y),
        r3y=p.return_3y,
        r3y_fmt=_pct(p.return_3y),
        r5y=p.return_5y,
        r5y_fmt=_pct(p.return_5y),
        dividends_total=client.dividends_total,
        dividends_total_fmt=_chf(client.dividends_total),
        dividend_yield_fmt=_pct(dividend_yield, 2),
        dividend_sources=len(client.dividends.by_security) if client.dividends else 0,
        # Charts
        alloc_chart=alloc_chart,
        value_history_chart=value_history_chart,
        holdings_chart=holdings_chart,
        div_year_chart=div_year_chart,
        # Asset allocation table
        asset_allocation=[
            {"name": a.name, "color": a.color or "#4f8cff",
             "value_fmt": _chf(a.value), "pct_fmt": f"{a.percentage:.1f}%"}
            for a in client.asset_allocation
        ],
        # Holdings
        holdings=holdings_rows,
        cash_accounts=cash_accounts,
        # Heatmap
        monthly_by_year={y: monthly_by_year[y] for y in monthly_years},
        monthly_years=monthly_years,
        # Dividends
        div_by_year=div_by_year,
        div_by_security=div_by_security,
    )

    return HTML(string=html_str).write_pdf()
