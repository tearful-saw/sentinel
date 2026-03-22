"""
Demo signal feeder for Sentinel.
Feeds real Base chain token addresses through the full pipeline
to demonstrate the system working without Telegram.
"""

import asyncio
from loguru import logger


# Real Base chain tokens with known liquidity
DEMO_TOKENS = [
    {
        "address": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
        "note": "BRETT - Popular Base memecoin, high liquidity",
    },
    {
        "address": "0x0578d8A44db98B23BF096A382e016e29a5Ce0ffe",
        "note": "HIGHER - Base native token",
    },
    {
        "address": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
        "note": "DEGEN - Base tipping token",
    },
    {
        "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "note": "USDC - Should be REJECTED (stablecoin blacklist)",
    },
    {
        "address": "0x0000000000000000000000000000000000000000",
        "note": "Zero address - Should be REJECTED",
    },
]


async def run_demo(strategy):
    """Feed demo tokens through the strategy pipeline."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  DEMO MODE - Processing {} sample signals".format(len(DEMO_TOKENS)))
    logger.info("  These are real Base chain tokens analyzed via DexScreener")
    logger.info("=" * 60)
    logger.info("")

    accepted = 0
    rejected = 0

    for i, token in enumerate(DEMO_TOKENS, 1):
        logger.info("[{}/{}] Signal: {} ".format(
            i, len(DEMO_TOKENS), token["note"]
        ))
        logger.info("  Address: {}".format(token["address"]))
        logger.info("-" * 50)

        result = await strategy.evaluate_signal(token["address"], source="demo")

        if result:
            accepted += 1
            logger.success("  -> Trade executed (dry-run)")
        else:
            rejected += 1
            logger.info("  -> Signal rejected")

        logger.info("")

        # Rate limit DexScreener API
        if i < len(DEMO_TOKENS):
            await asyncio.sleep(1.5)

    # Print final summary
    logger.info("")
    strategy.portfolio.print_summary()
    logger.info("")
    logger.info("Demo complete: {} accepted, {} rejected out of {} signals".format(
        accepted, rejected, len(DEMO_TOKENS)
    ))
