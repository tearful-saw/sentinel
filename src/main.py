#!/usr/bin/env python3
"""
Sentinel - Autonomous Alpha Signal Trading Agent

Two operating modes:
  SCANNER: Watches Base deployment channels → polls DexScreener until liquidity appears → LLM → trade
  SNIPER:  Monitors specific alpha channels → instant detection → analysis → trade

Usage:
    python main.py --demo                  # Demo with sample tokens
    python main.py --dry-run               # Scanner mode, simulated trades
    python main.py --dry-run --sniper      # Sniper mode (alpha channels), simulated trades
    python main.py --live                  # Scanner mode, real trades via Bankr
    python main.py --live --sniper         # Sniper mode, real trades via Bankr
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from analysis.token_analyzer import TokenAnalyzer
from analysis.llm_evaluator import LLMEvaluator
from analysis.security_checker import SecurityChecker
from strategy.signal_strategy import SignalStrategy
from traders.uniswap_executor import UniswapExecutor
from monitoring.portfolio import Portfolio
from detectors.contract_detector import ContractDetector


def setup_logging(level):
    # type: (str) -> None
    logger.remove()
    fmt = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, format=fmt, level=level, colorize=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sentinel - Autonomous Alpha Signal Trading Agent"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Real monitoring, simulated trades")
    group.add_argument("--demo", action="store_true",
                       help="Run demo signals (no Telegram needed)")
    group.add_argument("--live", action="store_true",
                       help="Real monitoring + real swaps via Bankr")
    parser.add_argument("--sniper", action="store_true",
                       help="Sniper mode: instant buy from alpha channels (default: scanner mode)")
    parser.add_argument("--no-llm", action="store_true",
                       help="Disable LLM evaluation (faster, less intelligent)")
    return parser.parse_args()


def extract_token_info(text):
    # type: (str) -> dict
    """Extract token name and symbol from deployment channel message."""
    info = {"name": "", "symbol": ""}
    # OttoBASEDeployments format: 🏷️ `Name` (`SYMBOL`)
    m = re.search(r'`([^`]+)`\s*\(`([^`]+)`\)', text)
    if m:
        info["name"] = m.group(1)
        info["symbol"] = m.group(2)
    # BasePairs format: **Name** ($SYMBOL)
    if not info["name"]:
        m = re.search(r'\*\*([^*]+)\*\*\s*\(\$([^)]+)\)', text)
        if m:
            info["name"] = m.group(1)
            info["symbol"] = m.group(2)
    return info


async def main():
    args = parse_args()
    config = load_config()

    dry_run = not args.live
    bankr_key = os.getenv("BANKR_API_KEY", "")
    uniswap_key = os.getenv("UNISWAP_API_KEY", "")
    is_sniper = args.sniper

    setup_logging(config.logging_config.level)

    mode_name = "SNIPER" if is_sniper else "SCANNER"

    logger.info("=" * 60)
    logger.info("  SENTINEL - Autonomous Alpha Signal Trading Agent")
    logger.info("  Mode: {} ({}) | LLM: {}".format(
        mode_name,
        "LIVE" if args.live else "DRY-RUN",
        "OFF" if args.no_llm else "Claude",
    ))
    logger.info("  Execution: Uniswap API + Bankr wallet")
    logger.info("=" * 60)

    # Initialize components
    analyzer = TokenAnalyzer(
        min_liquidity_usd=config.trading.min_liquidity_usd,
        target_chain="base",
    )

    trades_path = str(Path(__file__).parent.parent / "data" / "trades.json")
    portfolio = Portfolio(trades_file=trades_path)

    llm_evaluator = LLMEvaluator(
        model="sonnet",
        enabled=not args.no_llm,
        portfolio=portfolio,
    )

    # Get Bankr wallet address
    bankr_wallet = ""
    if bankr_key:
        try:
            import aiohttp as _aio
            async with _aio.ClientSession() as _s:
                async with _s.get("https://api.bankr.bot/agent/balances",
                                  headers={"X-API-Key": bankr_key}) as _r:
                    _d = await _r.json()
                    bankr_wallet = _d.get("evmAddress", "")
        except Exception:
            pass

    executor = UniswapExecutor(
        uniswap_api_key=uniswap_key,
        bankr_api_key=bankr_key,
        swapper_address=bankr_wallet,
        dry_run=dry_run,
    )

    security = SecurityChecker()

    strategy = SignalStrategy(
        analyzer=analyzer,
        llm_evaluator=llm_evaluator,
        executor=executor,
        portfolio=portfolio,
        trading_config=config.trading,
        security_checker=security,
    )

    # -- DEMO MODE --
    if args.demo:
        from demo_signals import run_demo
        await run_demo(strategy)
        return

    # -- Need Telegram for both scanner and sniper --
    if not config.telegram.api_id or not config.telegram.api_hash:
        logger.error("Telegram credentials not configured!")
        logger.error("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        logger.info("Use --demo mode to test without Telegram")
        sys.exit(1)

    from monitors.telegram_monitor import TelegramMonitor

    detector = ContractDetector()
    bot_start_time = datetime.now(timezone.utc)
    recent_signals = {}  # address -> timestamp for cross-channel dedup

    monitor = TelegramMonitor(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
        session_name=config.telegram.session_name,
        phone=config.telegram.phone,
    )

    if config.sources.telegram:
        monitor.add_sources(config.sources.telegram)
    else:
        logger.warning("No Telegram sources configured!")

    await monitor.start()

    if is_sniper:
        # ===== SNIPER MODE =====
        # Instant buy from alpha channels — same as before
        async def handle_message(text, source, timestamp):
            # type: (str, str, datetime) -> None
            if timestamp < bot_start_time - timedelta(seconds=30):
                return

            contract = detector.extract_from_dexscreener(text)
            if not contract:
                contract = detector.detect_first(text)
            if not contract:
                return
            if contract.chain.value != "evm":
                return

            addr_lower = contract.address.lower()
            now = datetime.now(timezone.utc)
            if addr_lower in recent_signals:
                if (now - recent_signals[addr_lower]).total_seconds() < 60:
                    return
            recent_signals[addr_lower] = now

            logger.info("SNIPER signal from {}: {}".format(
                source, contract.address[:20]
            ))
            await strategy.evaluate_signal(contract.address, source)

        monitor.on_message(handle_message)

        # Exit checker
        async def exit_checker():
            while True:
                await asyncio.sleep(30)
                try:
                    await strategy.check_exits()
                except Exception as e:
                    logger.error("Exit checker error: {}".format(e))

        logger.info("")
        logger.info("SNIPER mode: instant buy from {} channels".format(
            len(config.sources.telegram)
        ))
        logger.info("Press Ctrl+C to stop")

        try:
            await asyncio.gather(monitor.run(), exit_checker())
        except KeyboardInterrupt:
            pass
        finally:
            await monitor.stop()
            portfolio.print_summary()

    else:
        # ===== SCANNER MODE =====
        # Watch deployments → poll DexScreener → trade when liquidity appears
        from monitors.pair_scanner import PairScanner

        # Callback when scanner finds a qualified token
        async def on_qualified(address, source):
            logger.info("Scanner found qualified token: {}".format(address[:20]))
            await strategy.evaluate_signal(address, "scanner:{}".format(source))

        scanner = PairScanner(
            min_liquidity_usd=config.trading.min_liquidity_usd,
            on_qualified=on_qualified,
        )

        # Telegram handler: add deployments to scanner watchlist
        async def handle_message(text, source, timestamp):
            # type: (str, str, datetime) -> None
            if timestamp < bot_start_time - timedelta(seconds=30):
                return

            contract = detector.extract_from_dexscreener(text)
            if not contract:
                contract = detector.detect_first(text)
            if not contract:
                return
            if contract.chain.value != "evm":
                return

            addr_lower = contract.address.lower()
            now = datetime.now(timezone.utc)
            if addr_lower in recent_signals:
                if (now - recent_signals[addr_lower]).total_seconds() < 60:
                    return
            recent_signals[addr_lower] = now

            # Extract token name/symbol from message
            info = extract_token_info(text)

            scanner.add_to_watchlist(
                address=contract.address,
                name=info["name"],
                symbol=info["symbol"],
                source=source,
            )

        monitor.on_message(handle_message)

        # Exit checker
        async def exit_checker():
            while True:
                await asyncio.sleep(30)
                try:
                    await strategy.check_exits()
                except Exception as e:
                    logger.error("Exit checker error: {}".format(e))

        logger.info("")
        logger.info("SCANNER mode: watch deployments → poll DexScreener → trade")
        logger.info("Monitoring {} channels for new deploys".format(
            len(config.sources.telegram)
        ))
        logger.info("Min liquidity: ${:,.0f} | Poll interval: {}s".format(
            config.trading.min_liquidity_usd, scanner.POLL_INTERVAL
        ))
        logger.info("Press Ctrl+C to stop")

        try:
            await asyncio.gather(
                monitor.run(),
                scanner.run(),
                exit_checker(),
            )
        except KeyboardInterrupt:
            pass
        finally:
            scanner.stop()
            await monitor.stop()
            portfolio.print_summary()
            stats = scanner.get_stats()
            logger.info("Scanner stats: {} watched, {} qualified".format(
                stats["watchlist_size"], stats["qualified_total"]
            ))


if __name__ == "__main__":
    asyncio.run(main())
