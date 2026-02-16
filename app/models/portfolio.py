from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class TransactionType(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    INBOUND_DELIVERY = "INBOUND_DELIVERY"
    OUTBOUND_DELIVERY = "OUTBOUND_DELIVERY"
    SECURITY_TRANSFER = "SECURITY_TRANSFER"
    CASH_TRANSFER = "CASH_TRANSFER"
    DEPOSIT = "DEPOSIT"
    REMOVAL = "REMOVAL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    INTEREST_CHARGE = "INTEREST_CHARGE"
    TAX = "TAX"
    TAX_REFUND = "TAX_REFUND"
    FEE = "FEE"
    FEE_REFUND = "FEE_REFUND"


TRANSACTION_TYPE_MAP = {
    0: TransactionType.PURCHASE,
    1: TransactionType.SALE,
    2: TransactionType.INBOUND_DELIVERY,
    3: TransactionType.OUTBOUND_DELIVERY,
    4: TransactionType.SECURITY_TRANSFER,
    5: TransactionType.CASH_TRANSFER,
    6: TransactionType.DEPOSIT,
    7: TransactionType.REMOVAL,
    8: TransactionType.DIVIDEND,
    9: TransactionType.INTEREST,
    10: TransactionType.INTEREST_CHARGE,
    11: TransactionType.TAX,
    12: TransactionType.TAX_REFUND,
    13: TransactionType.FEE,
    14: TransactionType.FEE_REFUND,
}


class SecurityInfo(BaseModel):
    uuid: str
    name: str
    isin: str = ""
    ticker: str = ""
    currency: str = ""
    latest_price: float = 0.0
    latest_price_date: date | None = None


class AccountInfo(BaseModel):
    uuid: str
    name: str
    currency: str
    balance: float = 0.0


class PortfolioInfo(BaseModel):
    uuid: str
    name: str
    reference_account: str = ""


class TransactionInfo(BaseModel):
    uuid: str
    type: TransactionType
    date: datetime
    amount: float
    currency: str
    shares: float = 0.0
    security_uuid: str = ""
    security_name: str = ""
    note: str = ""
    account: str = ""
    portfolio: str = ""


class SecurityHolding(BaseModel):
    security: SecurityInfo
    shares: float
    current_value: float
    invested: float
    gain_loss: float
    gain_loss_pct: float
    currency: str
    category: str = ""
    volatility: float = 0.0
    annual_return: float = 0.0


class AssetCategory(BaseModel):
    name: str
    color: str
    value: float
    percentage: float
    holdings: list[SecurityHolding] = []


class MonthlyReturn(BaseModel):
    year: int
    month: int
    return_pct: float


class ValuePoint(BaseModel):
    date: str  # ISO date string for JSON serialization
    value: float


class PerformanceMetrics(BaseModel):
    ttwror: float = 0.0
    annual_return: float = 0.0
    ytd_return: float = 0.0
    return_1y: float = 0.0
    return_3y: float = 0.0
    return_5y: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_start: str = ""
    max_drawdown_end: str = ""


class DividendSummary(BaseModel):
    total: float = 0.0
    by_year: dict[int, float] = {}
    by_security: dict[str, float] = {}
    by_month: list[dict] = []  # [{year, month, amount}]


class ClientPortfolio(BaseModel):
    filename: str
    client_name: str
    base_currency: str
    total_value: float = 0.0
    total_invested: float = 0.0
    gain_loss: float = 0.0
    gain_loss_pct: float = 0.0
    dividends_total: float = 0.0
    fees_total: float = 0.0
    securities: list[SecurityInfo] = []
    accounts: list[AccountInfo] = []
    portfolios: list[PortfolioInfo] = []
    holdings: list[SecurityHolding] = []
    recent_transactions: list[TransactionInfo] = []
    all_transactions: list[TransactionInfo] = []
    last_updated: datetime | None = None
    # Extended data
    asset_allocation: list[AssetCategory] = []
    performance: PerformanceMetrics = PerformanceMetrics()
    monthly_returns: list[MonthlyReturn] = []
    value_history: list[ValuePoint] = []
    dividends: DividendSummary = DividendSummary()
    currency_breakdown: dict[str, float] = {}


class AggregatedOverview(BaseModel):
    total_value: float = 0.0
    total_invested: float = 0.0
    total_gain_loss: float = 0.0
    total_gain_loss_pct: float = 0.0
    total_dividends: float = 0.0
    client_count: int = 0
    clients: list[ClientPortfolio] = []
    top_holdings: list[SecurityHolding] = []
    currency_breakdown: dict[str, float] = {}
    recent_transactions: list[TransactionInfo] = []


class SyncStatus(BaseModel):
    last_sync: datetime | None = None
    next_sync: datetime | None = None
    files_synced: int = 0
    is_syncing: bool = False
    connected: bool = False
    errors: list[str] = []
