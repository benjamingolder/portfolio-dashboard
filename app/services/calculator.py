"""Financial calculations: performance, risk metrics, monthly returns."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from app.models.portfolio import (
    MonthlyReturn,
    PerformanceMetrics,
    ValuePoint,
)


def compute_portfolio_value_history(
    price_histories: dict[str, list[tuple[date, float]]],
    holdings_over_time: dict[str, list[tuple[date, float]]],
    cash_flows: list[tuple[date, float]],
) -> list[ValuePoint]:
    """Build daily portfolio value time series."""
    if not price_histories:
        return []

    all_dates: set[date] = set()
    for prices in price_histories.values():
        for d, _ in prices:
            all_dates.add(d)
    if not all_dates:
        return []

    sorted_dates = sorted(all_dates)

    price_lookup: dict[str, dict[date, float]] = {}
    for sec_uuid, prices in price_histories.items():
        price_lookup[sec_uuid] = dict(prices)

    # Build cumulative shares at each date
    shares_at_date: dict[str, dict[date, float]] = {}
    for sec_uuid, changes in holdings_over_time.items():
        sorted_changes = sorted(changes, key=lambda x: x[0])
        running = {}
        cumulative = 0.0
        change_idx = 0
        for d in sorted_dates:
            while change_idx < len(sorted_changes) and sorted_changes[change_idx][0] <= d:
                cumulative += sorted_changes[change_idx][1]
                change_idx += 1
            running[d] = max(cumulative, 0.0)
        shares_at_date[sec_uuid] = running

    history = []
    for d in sorted_dates:
        total = 0.0
        has_position = False
        for sec_uuid in price_histories:
            price = price_lookup[sec_uuid].get(d)
            shares = shares_at_date.get(sec_uuid, {}).get(d, 0.0)
            if price is not None and shares > 0.001:
                total += shares * price
                has_position = True
        if has_position and total > 0:
            history.append(ValuePoint(date=d.isoformat(), value=round(total, 2)))

    return history


def compute_performance_metrics(
    value_history: list[ValuePoint],
    total_invested: float,
    total_value: float,
    first_tx_date: date | None,
) -> PerformanceMetrics:
    """Compute performance metrics using simple return + recent volatility."""
    if total_invested <= 0:
        return PerformanceMetrics()

    # Simple total return
    total_return = ((total_value / total_invested) - 1.0) * 100

    # Annualized return
    today = date.today()
    if first_tx_date:
        days = (today - first_tx_date).days
    else:
        days = 365
    years = max(days / 365.25, 0.1)
    annual_return = ((1.0 + total_return / 100) ** (1.0 / years) - 1.0) * 100

    # Volatility from recent value history (last 252 trading days)
    volatility = 0.0
    sharpe = 0.0
    if len(value_history) > 20:
        recent = value_history[-260:]  # ~1 year
        returns = []
        for i in range(1, len(recent)):
            prev_v = recent[i - 1].value
            curr_v = recent[i].value
            if prev_v > 0:
                r = (curr_v / prev_v) - 1.0
                # Skip extreme outliers (position additions)
                if abs(r) < 0.15:
                    returns.append(r)
        if len(returns) > 10:
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance) * math.sqrt(252) * 100
            risk_free = 1.0
            sharpe = (annual_return - risk_free) / volatility if volatility > 0 else 0.0

    # Max Drawdown
    max_dd = 0.0
    dd_start_str = ""
    dd_end_str = ""
    if value_history:
        peak = value_history[0].value
        peak_date = value_history[0].date
        for vp in value_history:
            if vp.value > peak:
                peak = vp.value
                peak_date = vp.date
            dd = (peak - vp.value) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                dd_start_str = peak_date
                dd_end_str = vp.date

    # Period returns from value history
    def period_return(start_date: date) -> float:
        if not value_history:
            return 0.0
        start_val = None
        end_val = value_history[-1].value
        for vp in value_history:
            d = date.fromisoformat(vp.date)
            if d >= start_date:
                start_val = vp.value
                break
        if start_val and start_val > 0:
            return ((end_val / start_val) - 1.0) * 100
        return 0.0

    last_date = date.fromisoformat(value_history[-1].date) if value_history else today
    ytd_start = date(last_date.year, 1, 1)

    return PerformanceMetrics(
        ttwror=round(total_return, 2),
        annual_return=round(annual_return, 2),
        ytd_return=round(period_return(ytd_start), 2),
        return_1y=round(period_return(last_date - timedelta(days=365)), 2),
        return_3y=round(period_return(last_date - timedelta(days=3 * 365)), 2),
        return_5y=round(period_return(last_date - timedelta(days=5 * 365)), 2),
        volatility=round(volatility, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown=round(max_dd, 2),
        max_drawdown_start=dd_start_str,
        max_drawdown_end=dd_end_str,
    )


def compute_monthly_returns(value_history: list[ValuePoint]) -> list[MonthlyReturn]:
    """Compute monthly returns for heatmap."""
    if len(value_history) < 2:
        return []

    monthly_values: dict[tuple[int, int], list[tuple[date, float]]] = defaultdict(list)
    for vp in value_history:
        d = date.fromisoformat(vp.date)
        monthly_values[(d.year, d.month)].append((d, vp.value))

    sorted_months = sorted(monthly_values.keys())
    results = []
    for i, (year, month) in enumerate(sorted_months):
        vals = monthly_values[(year, month)]
        end_val = vals[-1][1]
        if i > 0:
            prev_key = sorted_months[i - 1]
            prev_vals = monthly_values[prev_key]
            start_val = prev_vals[-1][1]
        else:
            start_val = vals[0][1]

        if start_val > 0:
            ret = ((end_val / start_val) - 1.0) * 100
            # Cap extreme monthly returns from position changes
            ret = max(-50, min(100, ret))
        else:
            ret = 0.0
        results.append(MonthlyReturn(year=year, month=month, return_pct=round(ret, 2)))

    return results


def compute_security_volatility(prices: list[tuple[date, float]]) -> float:
    """Compute annualized volatility for a single security."""
    if len(prices) < 20:
        return 0.0
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1][1] > 0:
            r = (prices[i][1] / prices[i - 1][1]) - 1.0
            returns.append(r)
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 2)


def compute_security_annual_return(prices: list[tuple[date, float]]) -> float:
    """Compute annualized return for a single security."""
    if len(prices) < 2:
        return 0.0
    first_price = prices[0][1]
    last_price = prices[-1][1]
    if first_price <= 0:
        return 0.0
    days = (prices[-1][0] - prices[0][0]).days
    years = days / 365.25 if days > 0 else 1.0
    total_return = last_price / first_price
    annual = (total_return ** (1.0 / years) - 1.0) * 100
    return round(annual, 2)
