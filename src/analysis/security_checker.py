"""
Token security checker via GoPlus API.
Detects honeypots, hidden minting, proxy contracts, and other red flags.
Free API, no key required.
"""

import aiohttp
from dataclasses import dataclass
from typing import Optional
from loguru import logger


GOPLUS_URL = "https://api.gopluslabs.io/api/v1/token_security/8453"


@dataclass
class SecurityResult:
    address: str
    is_safe: bool
    is_honeypot: bool
    buy_tax: float
    sell_tax: float
    can_mint: bool
    hidden_owner: bool
    is_proxy: bool
    is_open_source: bool
    holder_count: int
    top10_holder_pct: float
    creator_pct: float
    risk_flags: list  # list of string warnings


class SecurityChecker:
    """Checks token security via GoPlus free API."""

    MAX_SELL_TAX = 10.0     # reject if sell tax > 10%
    MAX_TOP10_PCT = 0.80    # reject if top 10 hold > 80%

    async def check(self, address):
        # type: (str) -> Optional[SecurityResult]
        """Run security check on a token address (Base chain)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "{}?contract_addresses={}".format(GOPLUS_URL, address),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
        except Exception as e:
            logger.debug("GoPlus check failed: {}".format(e))
            return None

        result_data = data.get("result", {})
        if not result_data:
            return None

        # GoPlus returns lowercase address as key
        info = None
        for key, val in result_data.items():
            info = val
            break

        if not info:
            return None

        is_honeypot = info.get("is_honeypot") == "1"
        buy_tax = float(info.get("buy_tax") or 0) * 100
        sell_tax = float(info.get("sell_tax") or 0) * 100
        can_mint = info.get("is_mintable") == "1"
        hidden_owner = info.get("hidden_owner") == "1"
        is_proxy = info.get("is_proxy") == "1"
        is_open_source = info.get("is_open_source") == "1"
        holder_count = int(info.get("holder_count") or 0)
        top10 = float(info.get("top_10_holder_rate") or 0)
        creator_pct = float(info.get("creator_percent") or 0)

        # Build risk flags
        flags = []
        if is_honeypot:
            flags.append("HONEYPOT — cannot sell")
        if sell_tax > self.MAX_SELL_TAX:
            flags.append("High sell tax: {:.0f}%".format(sell_tax))
        if hidden_owner:
            flags.append("Hidden owner detected")
        if is_proxy:
            flags.append("Proxy contract (upgradeable)")
        if not is_open_source:
            flags.append("Closed source contract")
        if top10 > self.MAX_TOP10_PCT:
            flags.append("Top 10 hold {:.0f}%".format(top10 * 100))
        if creator_pct > 0.05:
            flags.append("Creator holds {:.1f}%".format(creator_pct * 100))

        is_safe = not is_honeypot and sell_tax <= self.MAX_SELL_TAX and not hidden_owner

        result = SecurityResult(
            address=address,
            is_safe=is_safe,
            is_honeypot=is_honeypot,
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            can_mint=can_mint,
            hidden_owner=hidden_owner,
            is_proxy=is_proxy,
            is_open_source=is_open_source,
            holder_count=holder_count,
            top10_holder_pct=top10,
            creator_pct=creator_pct,
            risk_flags=flags,
        )

        if is_safe:
            logger.info("Security OK: {} | {} holders | tax: {:.0f}%/{:.0f}%{}".format(
                address[:16], holder_count, buy_tax, sell_tax,
                " | " + ", ".join(flags) if flags else "",
            ))
        else:
            logger.warning("Security FAIL: {} | {}".format(
                address[:16], " | ".join(flags),
            ))

        return result
