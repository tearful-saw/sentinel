"""
Trade executor using Uniswap Trading API.
Gets optimized quotes and builds swap transactions via the official Uniswap API.
Used alongside Bankr for transaction signing/submission.
"""

import os
import time
from typing import Optional, Dict, Any
from loguru import logger

import aiohttp


UNISWAP_API = "https://trade-api.gateway.uniswap.org/v1"
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_CHAIN_ID = 8453


class UniswapExecutor:
    """Gets quotes and builds swaps via Uniswap Trading API, executes via Bankr."""

    def __init__(self, uniswap_api_key, bankr_api_key="", swapper_address="", dry_run=True):
        self.uniswap_key = uniswap_api_key
        self.bankr_key = bankr_api_key
        self.swapper = swapper_address or "0x" + "0" * 40
        self.dry_run = dry_run

        mode = "DRY-RUN" if dry_run else "LIVE"
        logger.info("UniswapExecutor ready | Swapper: {}... | Mode: {}".format(
            self.swapper[:16], mode
        ))

    async def get_quote(self, token_in, token_out, amount_wei, chain_id=BASE_CHAIN_ID):
        # type: (str, str, int, int) -> Optional[Dict[str, Any]]
        """Get a swap quote from Uniswap API."""
        headers = {
            "x-api-key": self.uniswap_key,
            "Content-Type": "application/json",
        }

        body = {
            "type": "EXACT_INPUT",
            "tokenInChainId": chain_id,
            "tokenOutChainId": chain_id,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "amount": str(amount_wei),
            "swapper": self.swapper,
            "slippageTolerance": 0.5,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "{}/quote".format(UNISWAP_API),
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()

                    if resp.status != 200:
                        logger.error("Uniswap quote error {}: {}".format(
                            resp.status, data
                        ))
                        return None

                    return data
        except Exception as e:
            logger.error("Uniswap quote request failed: {}".format(e))
            return None

    async def buy_token(self, token_address, amount_eth=0.001, symbol=""):
        # type: (str, float, str) -> Dict[str, Any]
        """Get Uniswap quote for buying a token with ETH on Base."""
        amount_wei = int(amount_eth * 1e18)
        token_label = symbol if symbol else token_address[:16]

        logger.info("Uniswap quote: {} ETH → {} on Base".format(amount_eth, token_label))

        quote_data = await self.get_quote(
            token_in=WETH_BASE,
            token_out=token_address,
            amount_wei=amount_wei,
        )

        if not quote_data:
            return {"status": "error", "error": "No quote from Uniswap"}

        quote = quote_data.get("quote", {})
        output = quote.get("output", {})
        amount_out = output.get("amount", "0")
        gas_usd = quote.get("gasFeeUSD", "?")
        routing = quote_data.get("routing", "?")
        request_id = quote_data.get("requestId", "")

        # Extract route info
        route_info = ""
        routes = quote.get("route", [])
        if routes and routes[0]:
            first_hop = routes[0][0]
            pool_type = first_hop.get("type", "?")
            fee = first_hop.get("fee", "?")
            route_info = "{} fee={}".format(pool_type, fee)

        logger.info("Uniswap quote: {} ETH → {} tokens | Gas: ${} | Route: {} | {}".format(
            amount_eth, amount_out, gas_usd, routing, route_info
        ))

        if self.dry_run:
            logger.info("[DRY-RUN] Would execute Uniswap swap via Bankr")
            return {
                "status": "dry-run",
                "action": "buy",
                "amount_eth": amount_eth,
                "amount_out": amount_out,
                "token": token_address,
                "symbol": symbol,
                "gas_usd": gas_usd,
                "routing": routing,
                "route_info": route_info,
                "request_id": request_id,
                "uniswap_quote": True,
            }

        # Live mode: execute via Bankr with the Uniswap-quoted parameters
        if self.bankr_key:
            return await self._execute_via_bankr(token_address, amount_eth, symbol)

        return {"status": "error", "error": "No execution method configured"}

    async def sell_token(self, token_address, symbol="", percentage=100):
        # type: (str, str, int) -> Dict[str, Any]
        """Sell token for ETH."""
        token_label = symbol if symbol else token_address[:16]

        if self.dry_run:
            logger.info("[DRY-RUN] Would sell {}% of {} via Uniswap on Base".format(
                percentage, token_label
            ))
            return {
                "status": "dry-run",
                "action": "sell",
                "token": token_address,
                "symbol": symbol,
                "percentage": percentage,
                "uniswap_quote": True,
            }

        if self.bankr_key:
            return await self._execute_via_bankr_sell(token_address, symbol, percentage)

        return {"status": "error", "error": "No execution method configured"}

    async def _execute_via_bankr(self, token_address, amount_eth, symbol):
        # type: (str, float, str) -> Dict[str, Any]
        """Execute swap via Bankr natural language API."""
        import asyncio

        headers = {
            "X-API-Key": self.bankr_key,
            "Content-Type": "application/json",
        }

        prompt = "Buy ${:.2f} worth of {} on Base".format(amount_eth * 2077, token_address)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.bankr.bot/agent/prompt",
                headers=headers,
                json={"prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

            if not data.get("success"):
                return {"status": "error", "error": str(data)}

            job_id = data["jobId"]

            for _ in range(30):
                await asyncio.sleep(2)
                async with session.get(
                    "https://api.bankr.bot/agent/job/{}".format(job_id),
                    headers=headers,
                ) as resp:
                    result = await resp.json()

                if result.get("status") == "completed":
                    logger.success("Bankr executed: {}".format(
                        result.get("response", "")[:100]
                    ))
                    return {
                        "status": "success",
                        "action": "buy",
                        "response": result.get("response", ""),
                        "job_id": job_id,
                    }
                elif result.get("status") in ("failed", "cancelled"):
                    return {"status": "error", "error": result.get("response", "")}

        return {"status": "error", "error": "Timeout"}

    async def _execute_via_bankr_sell(self, token_address, symbol, percentage):
        # type: (str, str, int) -> Dict[str, Any]
        """Sell via Bankr."""
        import asyncio

        headers = {
            "X-API-Key": self.bankr_key,
            "Content-Type": "application/json",
        }

        if percentage >= 100:
            prompt = "Sell all my {} on Base".format(token_address)
        else:
            prompt = "Sell {}% of my {} on Base".format(percentage, token_address)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.bankr.bot/agent/prompt",
                headers=headers,
                json={"prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

            if not data.get("success"):
                return {"status": "error", "error": str(data)}

            job_id = data["jobId"]

            for _ in range(30):
                await asyncio.sleep(2)
                async with session.get(
                    "https://api.bankr.bot/agent/job/{}".format(job_id),
                    headers=headers,
                ) as resp:
                    result = await resp.json()

                if result.get("status") == "completed":
                    return {"status": "success", "action": "sell", "response": result.get("response", "")}
                elif result.get("status") in ("failed", "cancelled"):
                    return {"status": "error", "error": result.get("response", "")}

        return {"status": "error", "error": "Timeout"}

    async def get_eth_balance(self):
        # type: () -> float
        """Get ETH balance via Bankr."""
        if not self.bankr_key:
            return 0.0

        headers = {"X-API-Key": self.bankr_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.bankr.bot/agent/balances",
                headers=headers,
            ) as resp:
                data = await resp.json()
                base = data.get("balances", {}).get("base", {})
                return float(base.get("nativeBalance", "0")) / 1e18
