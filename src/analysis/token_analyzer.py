"""
Token analyzer using DexScreener API.
Evaluates whether a detected token is safe and liquid enough to trade.
"""

import aiohttp
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class AnalysisResult:
    address: str
    symbol: str
    name: str
    chain: str
    pair_address: str
    liquidity_usd: float
    price_usd: float
    volume_24h: float
    passed: bool
    reject_reason: str


class TokenAnalyzer:
    DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"

    # Never trade these (stablecoins, wrappers on Base)
    SKIP_ADDRESSES = {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC
        "0x4200000000000000000000000000000000000006",    # WETH
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",  # DAI
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",  # USDbC
        "0x0000000000000000000000000000000000000000",    # Zero address
    }

    def __init__(self, min_liquidity_usd=5000.0, target_chain="base"):
        self.min_liquidity_usd = min_liquidity_usd
        self.target_chain = target_chain

    def _fail(self, address, reason):
        # type: (str, str) -> AnalysisResult
        return AnalysisResult(
            address=address, symbol="", name="", chain="",
            pair_address="", liquidity_usd=0, price_usd=0,
            volume_24h=0, passed=False, reject_reason=reason,
        )

    async def analyze(self, address):
        # type: (str) -> AnalysisResult
        """Fetch DexScreener data and evaluate token for trading."""
        if address.lower() in self.SKIP_ADDRESSES:
            logger.debug("Skip blacklisted address: {}".format(address[:16]))
            return self._fail(address, "Blacklisted stablecoin/wrapper")

        url = self.DEXSCREENER_URL.format(address)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return self._fail(address, "DexScreener API error: {}".format(resp.status))
                    data = await resp.json()
        except Exception as e:
            return self._fail(address, "DexScreener request failed: {}".format(e))

        pairs = data.get("pairs") or []
        if not pairs:
            return self._fail(address, "No pairs found on DexScreener")

        # Find best Base chain pair by liquidity
        base_pairs = [p for p in pairs if p.get("chainId") == self.target_chain]
        if not base_pairs:
            # Accept any chain pair for analysis, but note it
            base_pairs = pairs

        best = max(base_pairs, key=lambda p: float(
            (p.get("liquidity") or {}).get("usd", 0)
        ))

        liquidity = float((best.get("liquidity") or {}).get("usd", 0))
        price = float(best.get("priceUsd") or 0)
        volume = float((best.get("volume") or {}).get("h24", 0))
        chain_id = best.get("chainId", "unknown")

        base_token = best.get("baseToken") or {}
        symbol = base_token.get("symbol", "???")
        name = base_token.get("name", "Unknown")
        pair_address = best.get("pairAddress", "")

        # Evaluate
        passed = True
        reject_reason = ""

        if liquidity < self.min_liquidity_usd:
            passed = False
            reject_reason = "Liquidity ${:,.0f} < ${:,.0f} min".format(
                liquidity, self.min_liquidity_usd
            )
        elif chain_id != self.target_chain:
            passed = False
            reject_reason = "No {} pair (best: {})".format(self.target_chain, chain_id)

        result = AnalysisResult(
            address=address,
            symbol=symbol,
            name=name,
            chain=chain_id,
            pair_address=pair_address,
            liquidity_usd=liquidity,
            price_usd=price,
            volume_24h=volume,
            passed=passed,
            reject_reason=reject_reason,
        )

        if passed:
            logger.success(
                "PASS: {} ({}) | Liq: ${:,.0f} | Vol 24h: ${:,.0f} | ${:.8f}".format(
                    symbol, name[:20], liquidity, volume, price
                )
            )
        else:
            logger.info(
                "REJECT: {} | {}".format(address[:20], reject_reason)
            )

        return result
