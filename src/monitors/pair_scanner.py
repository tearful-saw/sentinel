"""
New pair scanner for Base chain.
Two strategies:
1. Watches tokens from Telegram deployment channels, polls DexScreener until liquidity appears
2. Periodically scans DexScreener for trending new pairs on Base

Feeds qualified tokens into the trading pipeline.
"""

import asyncio
import time
from typing import Dict, List, Optional, Callable, Set
from datetime import datetime, timezone
from dataclasses import dataclass

import aiohttp
from loguru import logger


@dataclass
class WatchedToken:
    address: str
    name: str
    symbol: str
    discovered_at: float  # unix timestamp
    source: str
    checks: int = 0
    last_check: float = 0


class PairScanner:
    """Scans for new Base pairs with liquidity via DexScreener polling."""

    DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/tokens/v1/base/{}"
    DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q={}"

    MAX_WATCH_AGE = 3600       # drop from watchlist after 1 hour
    POLL_INTERVAL = 30         # seconds between DexScreener checks
    BATCH_SIZE = 20            # max tokens per API call
    MAX_CHECKS = 60            # stop checking after 60 attempts (30 min)

    def __init__(
        self,
        min_liquidity_usd=5000.0,
        min_volume_usd=0,
        on_qualified=None,       # async callback(address, source)
    ):
        self.min_liquidity = min_liquidity_usd
        self.min_volume = min_volume_usd
        self.on_qualified = on_qualified

        self.watchlist = {}       # type: Dict[str, WatchedToken]
        self.qualified = set()    # type: Set[str]  # already sent to pipeline
        self._running = False

    def add_to_watchlist(self, address, name="", symbol="", source="telegram"):
        # type: (str, str, str, str) -> None
        """Add a newly deployed token to the watchlist."""
        addr = address.lower()
        if addr in self.watchlist or addr in self.qualified:
            return

        self.watchlist[addr] = WatchedToken(
            address=address,
            name=name,
            symbol=symbol or "???",
            discovered_at=time.time(),
            source=source,
        )
        logger.debug("Watchlist +{} ({}) | Total: {}".format(
            symbol or address[:16], source, len(self.watchlist)
        ))

    def _cleanup_watchlist(self):
        # type: () -> None
        """Remove stale entries from watchlist."""
        now = time.time()
        expired = [
            addr for addr, t in self.watchlist.items()
            if (now - t.discovered_at > self.MAX_WATCH_AGE) or (t.checks >= self.MAX_CHECKS)
        ]
        for addr in expired:
            del self.watchlist[addr]

    async def _check_batch(self, addresses):
        # type: (List[str]) -> List[dict]
        """Query DexScreener for a batch of token addresses."""
        addr_str = ",".join(addresses)
        url = self.DEXSCREENER_TOKENS_URL.format(addr_str)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug("DexScreener batch check error: {}".format(e))
            return []

    async def _poll_watchlist(self):
        # type: () -> None
        """Check all watched tokens for liquidity."""
        self._cleanup_watchlist()

        if not self.watchlist:
            return

        addresses = list(self.watchlist.keys())
        now = time.time()

        # Process in batches
        for i in range(0, len(addresses), self.BATCH_SIZE):
            batch = addresses[i:i + self.BATCH_SIZE]

            # Use original case addresses for API
            original_addrs = [self.watchlist[a].address for a in batch if a in self.watchlist]
            if not original_addrs:
                continue

            pairs = await self._check_batch(original_addrs)

            # Map pair results back to watched tokens
            # DexScreener returns pairs — match via both baseToken and quoteToken addresses
            for pair in pairs:
                chain = pair.get("chainId", "")
                if chain != "base":
                    continue

                liquidity = float((pair.get("liquidity") or {}).get("usd", 0))
                volume = float((pair.get("volume") or {}).get("h24", 0))
                base_token = pair.get("baseToken") or {}
                quote_token = pair.get("quoteToken") or {}

                # Match against watchlist by either base or quote token address
                matched_addr = None
                for addr_candidate in [base_token.get("address", ""), quote_token.get("address", "")]:
                    if addr_candidate.lower() in self.watchlist:
                        matched_addr = addr_candidate.lower()
                        break

                if not matched_addr:
                    continue

                watched = self.watchlist[matched_addr]
                watched.checks += 1
                watched.last_check = now

                if liquidity >= self.min_liquidity and matched_addr not in self.qualified:
                    self.qualified.add(matched_addr)
                    age = now - watched.discovered_at

                    # Use whichever token is NOT WETH as the symbol
                    symbol = base_token.get("symbol", "?")
                    name = base_token.get("name", "")[:20]
                    if symbol in ("WETH", "ETH"):
                        symbol = quote_token.get("symbol", "?")
                        name = quote_token.get("name", "")[:20]

                    logger.success(
                        "QUALIFIED: {} ({}) | Liq: ${:,.0f} | Vol: ${:,.0f} | "
                        "Age: {:.0f}s | Source: {}".format(
                            symbol, name, liquidity, volume, age, watched.source,
                        )
                    )

                    # Remove from watchlist
                    del self.watchlist[matched_addr]

                    # Callback with the original address
                    if self.on_qualified:
                        await self.on_qualified(watched.address, watched.source)

            # Rate limit between batches
            if i + self.BATCH_SIZE < len(addresses):
                await asyncio.sleep(1)

    async def run(self):
        # type: () -> None
        """Main polling loop."""
        self._running = True
        logger.info("Pair scanner started | Poll: {}s | Min liq: ${:,.0f}".format(
            self.POLL_INTERVAL, self.min_liquidity
        ))

        while self._running:
            try:
                if self.watchlist:
                    await self._poll_watchlist()
                    wl_size = len(self.watchlist)
                    if wl_size > 0:
                        logger.debug("Watchlist: {} tokens pending".format(wl_size))
            except Exception as e:
                logger.error("Scanner error: {}".format(e))

            await asyncio.sleep(self.POLL_INTERVAL)

    def stop(self):
        # type: () -> None
        self._running = False

    def get_stats(self):
        # type: () -> dict
        return {
            "watchlist_size": len(self.watchlist),
            "qualified_total": len(self.qualified),
        }
