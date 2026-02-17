from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class TransactionArt(str, Enum):
    BELASTUNG = "Belastung"
    GUTSCHRIFT = "Gutschrift"


class FinanceTransaction(BaseModel):
    id: int
    datum: date
    konto: str = ""
    titel: str = ""
    detail_beschrieb: str = ""
    empfaenger: str = ""
    art: TransactionArt
    kategorie: str = "Sonstige"
    betrag: float  # always positive
    betrag_vorzeichen: float  # negative for Belastung


class FinanceSummary(BaseModel):
    total_einnahmen: float = 0.0
    total_ausgaben: float = 0.0
    saldo: float = 0.0
    anzahl_transaktionen: int = 0


class MonthlyFinanceData(BaseModel):
    monat: str  # "YYYY-MM"
    einnahmen: float = 0.0
    ausgaben: float = 0.0
    saldo: float = 0.0


class CategoryData(BaseModel):
    kategorie: str
    betrag: float = 0.0
    anzahl: int = 0


class FinanceOverview(BaseModel):
    summary: FinanceSummary = FinanceSummary()
    monthly: list[MonthlyFinanceData] = []
    categories: list[CategoryData] = []
    konten: list[str] = []
    kategorien: list[str] = []
    last_sync: datetime | None = None
