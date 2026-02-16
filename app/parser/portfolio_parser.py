from __future__ import annotations

import io
import logging
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from app.models.portfolio import (
    TRANSACTION_TYPE_MAP,
    AccountInfo,
    AssetCategory,
    ClientPortfolio,
    DividendSummary,
    PortfolioInfo,
    SecurityHolding,
    SecurityInfo,
    TransactionInfo,
    TransactionType,
)
from app.parser.client_pb2 import PClient
from app.services.calculator import (
    compute_monthly_returns,
    compute_performance_metrics,
    compute_portfolio_value_history,
    compute_security_annual_return,
    compute_security_volatility,
)
from datetime import date as date_type

logger = logging.getLogger(__name__)

SIGNATURE = b"PPPBV1"

BUY_TYPES = {
    TransactionType.PURCHASE,
    TransactionType.INBOUND_DELIVERY,
}
SELL_TYPES = {
    TransactionType.SALE,
    TransactionType.OUTBOUND_DELIVERY,
}

EPOCH_BASE = date(1970, 1, 1).toordinal()


def _epoch_day_to_date(epoch_day: int) -> date:
    return date.fromordinal(EPOCH_BASE + epoch_day)


def _timestamp_to_datetime(ts) -> datetime:
    if ts.seconds:
        return datetime.fromtimestamp(ts.seconds, tz=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_protobuf(data: bytes) -> PClient:
    if not data.startswith(SIGNATURE):
        raise ValueError("Not a valid Portfolio Performance file (missing PPPBV1 header)")
    client = PClient()
    client.ParseFromString(data[len(SIGNATURE):])
    return client


def parse_portfolio_file(filepath: Path) -> ClientPortfolio:
    """Parse a .portfolio file and return a ClientPortfolio with computed metrics."""
    raw = filepath.read_bytes()

    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            inner = zf.read("data.portfolio")
        pb_client = _parse_protobuf(inner)
    elif raw[:6] == SIGNATURE:
        pb_client = _parse_protobuf(raw)
    else:
        raise ValueError(f"Unknown file format for {filepath.name}")

    return _build_client_portfolio(filepath.name, pb_client)


def _build_client_portfolio(filename: str, pb: PClient) -> ClientPortfolio:
    # ── Securities ──
    securities_map: dict[str, SecurityInfo] = {}
    price_histories: dict[str, list[tuple[date, float]]] = {}

    for s in pb.securities:
        latest_price = 0.0
        latest_date = None
        prices = []
        for p in s.prices:
            d = _epoch_day_to_date(p.date)
            price = p.close / 1_0000_0000
            prices.append((d, price))
        if prices:
            latest_price = prices[-1][1]
            latest_date = prices[-1][0]
        price_histories[s.uuid] = prices

        securities_map[s.uuid] = SecurityInfo(
            uuid=s.uuid,
            name=s.name,
            isin=s.isin or "",
            ticker=s.tickerSymbol or "",
            currency=s.currencyCode or "",
            latest_price=latest_price,
            latest_price_date=latest_date,
        )

    # ── Accounts ──
    accounts_map: dict[str, AccountInfo] = {}
    for a in pb.accounts:
        accounts_map[a.uuid] = AccountInfo(uuid=a.uuid, name=a.name, currency=a.currencyCode)

    # ── Portfolios ──
    portfolios_map: dict[str, PortfolioInfo] = {}
    for p in pb.portfolios:
        portfolios_map[p.uuid] = PortfolioInfo(
            uuid=p.uuid, name=p.name, reference_account=p.referenceAccount or ""
        )

    # ── Transactions ──
    transactions: list[TransactionInfo] = []
    for t in pb.transactions:
        tx_type = TRANSACTION_TYPE_MAP.get(t.type, TransactionType.PURCHASE)
        sec_name = securities_map[t.security].name if t.security and t.security in securities_map else ""
        acc_name = accounts_map[t.account].name if t.account and t.account in accounts_map else ""
        port_name = portfolios_map[t.portfolio].name if t.portfolio and t.portfolio in portfolios_map else ""

        transactions.append(TransactionInfo(
            uuid=t.uuid,
            type=tx_type,
            date=_timestamp_to_datetime(t.date),
            amount=t.amount / 100,
            currency=t.currencyCode,
            shares=t.shares / 1_0000_0000 if t.shares else 0.0,
            security_uuid=t.security or "",
            security_name=sec_name,
            note=t.note or "",
            account=acc_name,
            portfolio=port_name,
        ))

    transactions.sort(key=lambda x: x.date, reverse=True)

    # ── Holdings ──
    shares_held: dict[str, float] = defaultdict(float)
    cost_basis: dict[str, float] = defaultdict(float)
    # Track holdings changes over time for value history
    holdings_changes: dict[str, list[tuple[date, float]]] = defaultdict(list)

    for tx in sorted(transactions, key=lambda x: x.date):
        if not tx.security_uuid:
            continue
        tx_date = tx.date.date() if isinstance(tx.date, datetime) else tx.date
        if tx.type in BUY_TYPES:
            shares_held[tx.security_uuid] += tx.shares
            cost_basis[tx.security_uuid] += tx.amount
            holdings_changes[tx.security_uuid].append((tx_date, tx.shares))
        elif tx.type in SELL_TYPES:
            shares_held[tx.security_uuid] -= tx.shares
            cost_basis[tx.security_uuid] -= tx.amount
            holdings_changes[tx.security_uuid].append((tx_date, -tx.shares))

    # ── Taxonomy → Asset Allocation ──
    taxonomy_map: dict[str, tuple[str, str]] = {}  # security_uuid -> (category_name, color)
    account_categories: dict[str, tuple[str, str]] = {}  # account_uuid -> (category_name, color)
    for tax in pb.taxonomies:
        for cls in tax.classifications:
            for assignment in cls.assignments:
                vehicle = assignment.investmentVehicle
                if vehicle in securities_map:
                    taxonomy_map[vehicle] = (cls.name, cls.color)
                elif vehicle in accounts_map:
                    account_categories[vehicle] = (cls.name, cls.color)

    # ── Account balances ──
    account_balances: dict[str, float] = defaultdict(float)
    for tx in transactions:
        if not tx.account:
            continue
        # Find account UUID from name
        acc_uuid = None
        for uid, acc in accounts_map.items():
            if acc.name == tx.account:
                acc_uuid = uid
                break
        if not acc_uuid:
            continue
        if tx.type == TransactionType.DEPOSIT:
            account_balances[acc_uuid] += tx.amount
        elif tx.type == TransactionType.REMOVAL:
            account_balances[acc_uuid] -= tx.amount
        elif tx.type == TransactionType.DIVIDEND:
            account_balances[acc_uuid] += tx.amount
        elif tx.type == TransactionType.INTEREST:
            account_balances[acc_uuid] += tx.amount
        elif tx.type in (TransactionType.FEE, TransactionType.TAX, TransactionType.INTEREST_CHARGE):
            account_balances[acc_uuid] -= tx.amount
        elif tx.type in BUY_TYPES:
            account_balances[acc_uuid] -= tx.amount
        elif tx.type in SELL_TYPES:
            account_balances[acc_uuid] += tx.amount

    for uid, acc in accounts_map.items():
        acc.balance = round(account_balances.get(uid, 0.0), 2)

    # ── Build Holdings with categories and risk metrics ──
    holdings: list[SecurityHolding] = []
    total_value = 0.0
    total_invested = 0.0

    for sec_uuid, shares in shares_held.items():
        if shares <= 0.001:
            continue
        sec = securities_map.get(sec_uuid)
        if not sec:
            continue
        current_value = shares * sec.latest_price
        invested = cost_basis.get(sec_uuid, 0.0)
        gain = current_value - invested
        gain_pct = (gain / invested * 100) if invested > 0 else 0.0

        category_name = taxonomy_map.get(sec_uuid, ("Sonstige", "#666666"))[0]

        prices = price_histories.get(sec_uuid, [])
        vol = compute_security_volatility(prices)
        ann_ret = compute_security_annual_return(prices)

        holdings.append(SecurityHolding(
            security=sec,
            shares=round(shares, 4),
            current_value=round(current_value, 2),
            invested=round(invested, 2),
            gain_loss=round(gain, 2),
            gain_loss_pct=round(gain_pct, 2),
            currency=sec.currency,
            category=category_name,
            volatility=vol,
            annual_return=ann_ret,
        ))
        total_value += current_value
        total_invested += invested

    holdings.sort(key=lambda h: h.current_value, reverse=True)

    # ── Asset Allocation ──
    cat_data: dict[str, dict] = {}
    for h in holdings:
        cat = h.category
        if cat not in cat_data:
            color = taxonomy_map.get(h.security.uuid, ("", "#666666"))[1]
            cat_data[cat] = {"name": cat, "color": color, "value": 0.0, "holdings": []}
        cat_data[cat]["value"] += h.current_value
        cat_data[cat]["holdings"].append(h)

    # Add cash as a category
    cash_total = sum(acc.balance for acc in accounts_map.values() if acc.balance > 0)
    if cash_total > 0:
        cat_data["Cash"] = {
            "name": "Cash",
            "color": "#91b3d8",
            "value": cash_total,
            "holdings": [],
        }

    total_with_cash = total_value + cash_total
    asset_allocation = []
    for data in sorted(cat_data.values(), key=lambda x: x["value"], reverse=True):
        pct = (data["value"] / total_with_cash * 100) if total_with_cash > 0 else 0.0
        asset_allocation.append(AssetCategory(
            name=data["name"],
            color=data["color"],
            value=round(data["value"], 2),
            percentage=round(pct, 1),
            holdings=data["holdings"],
        ))

    # ── Currency breakdown ──
    currency_breakdown: dict[str, float] = defaultdict(float)
    for h in holdings:
        currency_breakdown[h.currency] += h.current_value
    for acc in accounts_map.values():
        if acc.balance > 0:
            currency_breakdown[acc.currency] += acc.balance

    # ── Cash flows for performance calculation ──
    cash_flows: list[tuple[date, float]] = []
    for tx in transactions:
        tx_date = tx.date.date() if isinstance(tx.date, datetime) else tx.date
        if tx.type == TransactionType.DEPOSIT:
            cash_flows.append((tx_date, tx.amount))
        elif tx.type == TransactionType.REMOVAL:
            cash_flows.append((tx_date, -tx.amount))

    # ── Portfolio value history ──
    # Only use price histories for held securities
    held_prices = {uuid: prices for uuid, prices in price_histories.items() if shares_held.get(uuid, 0) > 0.001}
    value_history = compute_portfolio_value_history(held_prices, dict(holdings_changes), cash_flows)

    # Downsample to weekly if too many points
    if len(value_history) > 500:
        value_history = value_history[::5]

    # ── Performance metrics ──
    # Find first transaction date
    first_tx_date: date_type | None = None
    if transactions:
        oldest = min(transactions, key=lambda t: t.date)
        first_tx_date = oldest.date.date() if isinstance(oldest.date, datetime) else oldest.date
    performance = compute_performance_metrics(value_history, total_invested, total_value, first_tx_date)

    # ── Monthly returns ──
    monthly_returns = compute_monthly_returns(value_history)

    # ── Dividends ──
    div_by_year: dict[int, float] = defaultdict(float)
    div_by_security: dict[str, float] = defaultdict(float)
    div_by_month: list[dict] = []
    div_monthly: dict[tuple[int, int], float] = defaultdict(float)

    for tx in transactions:
        if tx.type == TransactionType.DIVIDEND:
            yr = tx.date.year
            mo = tx.date.month
            div_by_year[yr] += tx.amount
            div_by_security[tx.security_name or "Unbekannt"] += tx.amount
            div_monthly[(yr, mo)] += tx.amount

    for (yr, mo), amt in sorted(div_monthly.items()):
        div_by_month.append({"year": yr, "month": mo, "amount": round(amt, 2)})

    dividends_total = sum(tx.amount for tx in transactions if tx.type == TransactionType.DIVIDEND)
    fees_total = sum(tx.amount for tx in transactions if tx.type == TransactionType.FEE)

    gain_loss = total_value - total_invested
    gain_loss_pct = (gain_loss / total_invested * 100) if total_invested > 0 else 0.0

    client_name = Path(filename).stem

    return ClientPortfolio(
        filename=filename,
        client_name=client_name,
        base_currency=pb.baseCurrency or "CHF",
        total_value=round(total_value, 2),
        total_invested=round(total_invested, 2),
        gain_loss=round(gain_loss, 2),
        gain_loss_pct=round(gain_loss_pct, 2),
        dividends_total=round(dividends_total, 2),
        fees_total=round(fees_total, 2),
        securities=list(securities_map.values()),
        accounts=list(accounts_map.values()),
        portfolios=list(portfolios_map.values()),
        holdings=holdings,
        recent_transactions=transactions[:20],
        all_transactions=transactions,
        asset_allocation=asset_allocation,
        performance=performance,
        monthly_returns=monthly_returns,
        value_history=value_history,
        dividends=DividendSummary(
            total=round(dividends_total, 2),
            by_year={k: round(v, 2) for k, v in div_by_year.items()},
            by_security={k: round(v, 2) for k, v in sorted(div_by_security.items(), key=lambda x: -x[1])},
            by_month=div_by_month,
        ),
        currency_breakdown=dict(currency_breakdown),
    )
