from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from app.models.portfolio import (
    AggregatedOverview,
    ClientPortfolio,
    SecurityHolding,
    SecurityInfo,
)
from app.parser.portfolio_parser import parse_portfolio_file

logger = logging.getLogger(__name__)


class AggregationService:
    def __init__(self) -> None:
        self.clients: dict[str, ClientPortfolio] = {}
        self.overview: AggregatedOverview = AggregatedOverview()

    def load_all(self, data_dir: str) -> None:
        """Load and parse all .portfolio files from the data directory."""
        path = Path(data_dir)
        if not path.exists():
            logger.warning("Data directory %s does not exist", data_dir)
            return

        files = list(path.glob("*.portfolio"))
        if not files:
            logger.info("No .portfolio files found in %s", data_dir)
            return

        logger.info("Loading %d portfolio files from %s", len(files), data_dir)
        new_clients: dict[str, ClientPortfolio] = {}
        for f in files:
            try:
                client = parse_portfolio_file(f)
                new_clients[f.name] = client
                logger.info("Loaded %s: value=%.2f %s", f.name, client.total_value, client.base_currency)
            except Exception:
                logger.exception("Failed to parse %s", f.name)

        self.clients = new_clients
        self._aggregate()

    def _aggregate(self) -> None:
        if not self.clients:
            self.overview = AggregatedOverview()
            return

        total_value = 0.0
        total_invested = 0.0
        total_dividends = 0.0
        all_transactions = []
        currency_values: dict[str, float] = defaultdict(float)

        # Aggregate holdings across clients
        holdings_agg: dict[str, dict] = {}  # security name -> aggregated data

        for client in self.clients.values():
            total_value += client.total_value
            total_invested += client.total_invested
            total_dividends += client.dividends_total
            all_transactions.extend(client.recent_transactions)

            for h in client.holdings:
                currency_values[h.currency] += h.current_value
                key = h.security.name
                if key in holdings_agg:
                    agg = holdings_agg[key]
                    agg["shares"] += h.shares
                    agg["current_value"] += h.current_value
                    agg["invested"] += h.invested
                else:
                    holdings_agg[key] = {
                        "security": h.security,
                        "shares": h.shares,
                        "current_value": h.current_value,
                        "invested": h.invested,
                        "currency": h.currency,
                    }

        # Build top holdings
        top_holdings = []
        for data in holdings_agg.values():
            invested = data["invested"]
            current = data["current_value"]
            gain = current - invested
            gain_pct = (gain / invested * 100) if invested > 0 else 0.0
            top_holdings.append(SecurityHolding(
                security=data["security"],
                shares=round(data["shares"], 4),
                current_value=round(current, 2),
                invested=round(invested, 2),
                gain_loss=round(gain, 2),
                gain_loss_pct=round(gain_pct, 2),
                currency=data["currency"],
            ))
        top_holdings.sort(key=lambda h: h.current_value, reverse=True)

        # Sort recent transactions by date
        all_transactions.sort(key=lambda t: t.date, reverse=True)

        total_gain = total_value - total_invested
        total_gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0.0

        # Client summaries (without full transaction lists)
        client_summaries = []
        for c in self.clients.values():
            summary = c.model_copy()
            summary.all_transactions = []  # Don't include in overview
            client_summaries.append(summary)
        client_summaries.sort(key=lambda c: c.total_value, reverse=True)

        self.overview = AggregatedOverview(
            total_value=round(total_value, 2),
            total_invested=round(total_invested, 2),
            total_gain_loss=round(total_gain, 2),
            total_gain_loss_pct=round(total_gain_pct, 2),
            total_dividends=round(total_dividends, 2),
            client_count=len(self.clients),
            clients=client_summaries,
            top_holdings=top_holdings[:20],
            currency_breakdown=dict(currency_values),
            recent_transactions=all_transactions[:30],
        )

    def get_client(self, filename: str) -> ClientPortfolio | None:
        return self.clients.get(filename)
