"""
Portfolio tracker and P&L calculator.
Records all trades to trades.json with entry/exit data.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from loguru import logger


class Portfolio:
    """Tracks trades and calculates P&L."""

    def __init__(self, trades_file="data/trades.json"):
        self.trades_file = Path(trades_file)
        self.trades = []  # type: List[dict]
        self._load()

    def _load(self):
        # type: () -> None
        if self.trades_file.exists():
            try:
                with open(self.trades_file) as f:
                    self.trades = json.load(f)
                logger.debug("Loaded {} trades from {}".format(
                    len(self.trades), self.trades_file
                ))
            except (json.JSONDecodeError, IOError):
                self.trades = []

    def _save(self):
        # type: () -> None
        self.trades_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trades_file, "w") as f:
            json.dump(self.trades, f, indent=2, default=str)

    def record_entry(self, token_address, symbol, amount_eth, entry_price, tx_result, source=""):
        # type: (str, str, float, float, dict, str) -> None
        """Record a new position entry (buy)."""
        trade = {
            "token": token_address,
            "symbol": symbol,
            "action": "BUY",
            "amount_eth": amount_eth,
            "entry_price": entry_price,
            "entry_timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "tx": tx_result,
            "status": "open",
        }
        self.trades.append(trade)
        self._save()
        logger.info("Trade recorded: BUY {} ({}) @ ${:.8f}".format(
            symbol, token_address[:16], entry_price
        ))

    def record_exit(self, token_address, exit_price, reason, tx_result):
        # type: (str, float, str, dict) -> None
        """Record position exit (sell)."""
        for trade in reversed(self.trades):
            if (trade.get("token", "").lower() == token_address.lower()
                    and trade.get("status") == "open"):
                trade["exit_price"] = exit_price
                trade["exit_reason"] = reason
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["exit_tx"] = tx_result
                trade["status"] = "closed"

                entry = trade.get("entry_price", 0)
                if entry > 0:
                    trade["pnl_pct"] = (exit_price / entry - 1) * 100
                else:
                    trade["pnl_pct"] = 0

                self._save()
                logger.info("Trade closed: {} {} | {} | P&L: {:.1f}%".format(
                    trade["symbol"], token_address[:16],
                    reason, trade["pnl_pct"]
                ))
                return

        logger.warning("No open trade found for {}".format(token_address[:16]))

    def get_open_positions(self):
        # type: () -> List[dict]
        return [t for t in self.trades if t.get("status") == "open"]

    def summary(self):
        # type: () -> dict
        """Calculate portfolio summary statistics."""
        total = len(self.trades)
        closed = [t for t in self.trades if t.get("status") == "closed"]
        open_positions = [t for t in self.trades if t.get("status") == "open"]
        wins = [t for t in closed if t.get("pnl_pct", 0) > 0]
        losses = [t for t in closed if t.get("pnl_pct", 0) <= 0]

        total_pnl = sum(t.get("pnl_pct", 0) for t in closed)
        avg_pnl = total_pnl / max(len(closed), 1)
        total_eth = sum(t.get("amount_eth", 0) for t in self.trades)

        return {
            "total_trades": total,
            "open_positions": len(open_positions),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / max(len(closed), 1) * 100,
            "avg_pnl_pct": avg_pnl,
            "total_pnl_pct": total_pnl,
            "total_eth_deployed": total_eth,
        }

    def print_summary(self):
        # type: () -> None
        """Print formatted portfolio summary."""
        s = self.summary()
        logger.info("=" * 50)
        logger.info("PORTFOLIO SUMMARY")
        logger.info("-" * 50)
        logger.info("Total trades:     {}".format(s["total_trades"]))
        logger.info("Open positions:   {}".format(s["open_positions"]))
        logger.info("Closed trades:    {}".format(s["closed_trades"]))
        logger.info("Wins / Losses:    {} / {}".format(s["wins"], s["losses"]))
        logger.info("Win rate:         {:.1f}%".format(s["win_rate"]))
        logger.info("Avg P&L:          {:.1f}%".format(s["avg_pnl_pct"]))
        logger.info("Total P&L:        {:.1f}%".format(s["total_pnl_pct"]))
        logger.info("ETH deployed:     {:.4f} ETH".format(s["total_eth_deployed"]))
        logger.info("=" * 50)
