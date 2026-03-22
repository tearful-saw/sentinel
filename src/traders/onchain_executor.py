"""
On-chain trade executor via Bankr API.
Handles buying and selling tokens on Base through natural language trading API.
Supports dry-run mode for simulation.
"""

import time
import json
import asyncio
from typing import Optional, Dict, Any
from loguru import logger

import aiohttp


BANKR_API = "https://api.bankr.bot"
BANKR_WALLET = "0xcd5c239cd4717778d326bd25781bf1b26825927a"


class OnChainExecutor:
    """Executes trades on Base via Bankr natural language API."""

    def __init__(self, api_key, dry_run=True):
        self.api_key = api_key
        self.dry_run = dry_run
        self.thread_id = None  # conversation continuity

        mode = "DRY-RUN" if dry_run else "LIVE"
        logger.info("Executor ready | Bankr API | Wallet: {}... | Mode: {}".format(
            BANKR_WALLET[:16], mode
        ))

    async def _prompt(self, prompt_text):
        # type: (str) -> Dict[str, Any]
        """Send prompt to Bankr API and wait for result."""
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        body = {"prompt": prompt_text}
        if self.thread_id:
            body["threadId"] = self.thread_id

        async with aiohttp.ClientSession() as session:
            # Submit job
            async with session.post(
                "{}/agent/prompt".format(BANKR_API),
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

            if not data.get("success"):
                logger.error("Bankr API error: {}".format(data))
                return {"status": "error", "error": data.get("error", "Unknown")}

            job_id = data["jobId"]
            self.thread_id = data.get("threadId", self.thread_id)

            # Poll for completion
            for _ in range(30):  # max 60 seconds
                await asyncio.sleep(2)
                async with session.get(
                    "{}/agent/job/{}".format(BANKR_API, job_id),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    result = await resp.json()

                status = result.get("status", "")
                if status == "completed":
                    return {
                        "status": "success",
                        "response": result.get("response", ""),
                        "job_id": job_id,
                        "processing_time": result.get("processingTime", 0),
                        "rich_data": result.get("richData", []),
                    }
                elif status in ("failed", "cancelled"):
                    return {
                        "status": "error",
                        "error": result.get("response", "Job {}".format(status)),
                        "job_id": job_id,
                    }

            return {"status": "error", "error": "Timeout waiting for job", "job_id": job_id}

    async def get_balances(self):
        # type: () -> Dict[str, Any]
        """Get wallet balances from Bankr."""
        headers = {"X-API-Key": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "{}/agent/balances".format(BANKR_API),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
        return data

    async def buy_token(self, token_address, amount_usd=5.0, symbol=""):
        # type: (str, float, str) -> Dict[str, Any]
        """Buy token on Base via Bankr."""
        token_label = symbol if symbol else token_address[:16]

        if self.dry_run:
            logger.info("[DRY-RUN] Would buy ${} of {} on Base".format(
                amount_usd, token_label
            ))
            logger.info("[DRY-RUN] Bankr prompt: 'Buy ${} of {} on Base'".format(
                amount_usd, token_address
            ))
            return {
                "status": "dry-run",
                "action": "buy",
                "amount_usd": amount_usd,
                "token": token_address,
                "symbol": symbol,
                "wallet": BANKR_WALLET,
            }

        prompt = "Buy ${} of {} on Base".format(amount_usd, token_address)
        logger.info("Bankr: {}".format(prompt))

        result = await self._prompt(prompt)

        if result["status"] == "success":
            logger.success("Bankr trade executed: {}".format(
                result.get("response", "")[:100]
            ))
        else:
            logger.error("Bankr trade failed: {}".format(result.get("error", "")))

        result["action"] = "buy"
        result["token"] = token_address
        result["amount_usd"] = amount_usd
        return result

    async def sell_token(self, token_address, symbol="", percentage=100):
        # type: (str, str, int) -> Dict[str, Any]
        """Sell token on Base via Bankr."""
        token_label = symbol if symbol else token_address[:16]

        if self.dry_run:
            logger.info("[DRY-RUN] Would sell {}% of {} on Base".format(
                percentage, token_label
            ))
            return {
                "status": "dry-run",
                "action": "sell",
                "token": token_address,
                "symbol": symbol,
                "percentage": percentage,
            }

        if percentage >= 100:
            prompt = "Sell all my {} on Base".format(token_address)
        else:
            prompt = "Sell {}% of my {} on Base".format(percentage, token_address)

        logger.info("Bankr: {}".format(prompt))
        result = await self._prompt(prompt)

        if result["status"] == "success":
            logger.success("Bankr sell executed: {}".format(
                result.get("response", "")[:100]
            ))
        else:
            logger.error("Bankr sell failed: {}".format(result.get("error", "")))

        result["action"] = "sell"
        result["token"] = token_address
        return result

    async def get_token_price(self, token_address):
        # type: (str) -> Optional[float]
        """Get token price via Bankr."""
        result = await self._prompt(
            "What is the current price of {} on Base? Just give me the USD price number.".format(
                token_address
            )
        )
        if result["status"] == "success":
            response = result.get("response", "")
            # Try to extract price from response
            import re
            match = re.search(r'\$?([\d.]+)', response)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
        return None
