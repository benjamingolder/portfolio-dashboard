from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from app.models.finance import (
    CategoryData,
    FinanceOverview,
    FinanceSummary,
    FinanceTransaction,
    MonthlyFinanceData,
    TransactionArt,
)
from app.sharepoint.client import SharePointClient

logger = logging.getLogger(__name__)

SELECT_FIELDS = [
    "ID", "Title", "Datum", "Konto", "DetailBeschrieb",
    "Empf_x00e4_nger_x0028_beiZahlung", "Art", "Kategorie", "Betrag",
]


class FinanceService:
    def __init__(self) -> None:
        self.transactions: list[FinanceTransaction] = []
        self.overview: FinanceOverview = FinanceOverview()

    async def sync(self, client: SharePointClient, site_id: str, list_name: str) -> None:
        """Fetch all transactions from SharePoint and recompute aggregates."""
        raw_items = await client.get_list_items(
            list_name=list_name,
            site_id=site_id,
            select_fields=SELECT_FIELDS,
        )
        self.transactions = [self._map_item(item, i) for i, item in enumerate(raw_items)]
        self.transactions.sort(key=lambda t: t.datum, reverse=True)
        self._aggregate()
        logger.info("Finance sync complete: %d transactions", len(self.transactions))

    def _map_item(self, fields: dict, index: int) -> FinanceTransaction:
        """Map Graph API list item fields to FinanceTransaction."""
        art_value = fields.get("Art", "Belastung")
        if isinstance(art_value, dict):
            art_value = art_value.get("Value", "Belastung")
        art = TransactionArt.GUTSCHRIFT if art_value == "Gutschrift" else TransactionArt.BELASTUNG

        betrag = abs(float(fields.get("Betrag", 0) or 0))

        kategorie = fields.get("Kategorie", "Sonstige")
        if isinstance(kategorie, dict):
            kategorie = kategorie.get("Value", "Sonstige")

        datum_raw = fields.get("Datum")
        if datum_raw:
            datum = date.fromisoformat(str(datum_raw)[:10])
        else:
            datum = date.today()

        return FinanceTransaction(
            id=fields.get("ID", index),
            datum=datum,
            konto=fields.get("Konto", "") or "",
            titel=fields.get("Title", "") or "",
            detail_beschrieb=fields.get("DetailBeschrieb", "") or "",
            empfaenger=fields.get("Empf_x00e4_nger_x0028_beiZahlung", "") or "",
            art=art,
            kategorie=kategorie or "Sonstige",
            betrag=betrag,
            betrag_vorzeichen=-betrag if art == TransactionArt.BELASTUNG else betrag,
        )

    def _aggregate(self) -> None:
        """Compute summary, monthly and category breakdowns."""
        total_ein = 0.0
        total_aus = 0.0
        monthly_map: dict[str, dict[str, float]] = defaultdict(lambda: {"ein": 0.0, "aus": 0.0})
        category_map: dict[str, dict[str, float]] = defaultdict(lambda: {"betrag": 0.0, "anzahl": 0})
        konten: set[str] = set()
        kategorien: set[str] = set()

        for t in self.transactions:
            if t.konto:
                konten.add(t.konto)
            kategorien.add(t.kategorie)

            key = f"{t.datum.year}-{t.datum.month:02d}"
            if t.art == TransactionArt.GUTSCHRIFT:
                total_ein += t.betrag
                monthly_map[key]["ein"] += t.betrag
            else:
                total_aus += t.betrag
                monthly_map[key]["aus"] += t.betrag
                cat = category_map[t.kategorie]
                cat["betrag"] += t.betrag
                cat["anzahl"] += 1

        summary = FinanceSummary(
            total_einnahmen=round(total_ein, 2),
            total_ausgaben=round(total_aus, 2),
            saldo=round(total_ein - total_aus, 2),
            anzahl_transaktionen=len(self.transactions),
        )

        monthly = sorted(
            [
                MonthlyFinanceData(
                    monat=m,
                    einnahmen=round(d["ein"], 2),
                    ausgaben=round(d["aus"], 2),
                    saldo=round(d["ein"] - d["aus"], 2),
                )
                for m, d in monthly_map.items()
            ],
            key=lambda x: x.monat,
        )

        categories = sorted(
            [
                CategoryData(
                    kategorie=k,
                    betrag=round(d["betrag"], 2),
                    anzahl=int(d["anzahl"]),
                )
                for k, d in category_map.items()
            ],
            key=lambda x: x.betrag,
            reverse=True,
        )

        self.overview = FinanceOverview(
            summary=summary,
            monthly=monthly,
            categories=categories,
            konten=sorted(konten),
            kategorien=sorted(kategorien),
            last_sync=datetime.now(timezone.utc),
        )

    def get_filtered(
        self,
        search: str = "",
        kategorie: str = "",
        art: str = "",
        konto: str = "",
        start_datum: str = "",
        end_datum: str = "",
    ) -> list[FinanceTransaction]:
        """Filter transactions based on criteria."""
        result = self.transactions
        if start_datum:
            sd = date.fromisoformat(start_datum)
            result = [t for t in result if t.datum >= sd]
        if end_datum:
            ed = date.fromisoformat(end_datum)
            result = [t for t in result if t.datum <= ed]
        if kategorie:
            result = [t for t in result if t.kategorie == kategorie]
        if konto:
            result = [t for t in result if t.konto == konto]
        if art:
            result = [t for t in result if t.art.value == art]
        if search:
            s = search.lower()
            result = [
                t for t in result
                if s in t.titel.lower()
                or s in t.empfaenger.lower()
                or s in t.detail_beschrieb.lower()
                or s in t.kategorie.lower()
            ]
        return result
