"""
Signal strategy engine.
Evaluates detected contracts via DexScreener + LLM, manages positions, handles exits.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
from loguru import logger


@dataclass
class Position:
    token_address: str
    symbol: str
    entry_price: float
    amount_usd: float
    entry_time: datetime
    take_profit_price: float
    stop_loss_price: float
    exit_deadline: datetime
    source: str = ""
    status: str = "open"


class SignalStrategy:
    """Orchestrates: detect -> security -> social -> analyze -> LLM evaluate -> execute -> track."""

    def __init__(self, analyzer, llm_evaluator, executor, portfolio, trading_config,
                 security_checker=None, social_checker=None):
        self.analyzer = analyzer
        self.llm = llm_evaluator
        self.executor = executor
        self.portfolio = portfolio
        self.config = trading_config
        self.security = security_checker
        self.social = social_checker
        self.positions = {}  # type: Dict[str, Position]

    async def evaluate_signal(self, contract_address, source="unknown"):
        # type: (str, str) -> bool
        """Full pipeline: DexScreener analyze -> LLM evaluate -> execute -> record."""
        addr_lower = contract_address.lower()

        # Check position limit
        open_count = sum(1 for p in self.positions.values() if p.status == "open")
        if open_count >= self.config.max_positions:
            logger.info("SKIP: Max positions reached ({}/{})".format(
                open_count, self.config.max_positions
            ))
            return False

        # Check duplicate
        if addr_lower in self.positions and self.positions[addr_lower].status == "open":
            logger.info("SKIP: Already have position in {}".format(
                self.positions[addr_lower].symbol
            ))
            return False

        # 1. DexScreener analysis
        logger.info("Analyzing {}...".format(contract_address[:20]))
        analysis = await self.analyzer.analyze(contract_address)

        if not analysis:
            logger.info("SKIP {}: No analysis data".format(contract_address[:16]))
            return False

        if not analysis.passed:
            logger.info("SKIP {}: {}".format(contract_address[:16], analysis.reject_reason))
            return False

        # 2. Security check (GoPlus) — before LLM to save inference
        if self.security:
            sec = await self.security.check(contract_address)
            if sec and not sec.is_safe:
                logger.warning("SECURITY REJECT {}: {}".format(
                    analysis.symbol, " | ".join(sec.risk_flags)
                ))
                return False

        # 3. Social verification (Twitter + smart money patterns)
        social_context = ""
        if self.social:
            try:
                soc = await self.social.check(analysis)
                if soc:
                    social_context = "\nSOCIAL VERIFICATION:\n"
                    if soc.twitter_exists:
                        social_context += "- Twitter: @{} | {} followers | {} tweets\n".format(
                            soc.twitter_handle, soc.twitter_followers, soc.twitter_tweets
                        )
                        social_context += "- Bio: {}\n".format(soc.twitter_description[:80])
                    else:
                        social_context += "- Twitter: NOT VERIFIED (no account found)\n"
                    social_context += "- Buy pressure 1h: {:.0%} | Volume acceleration: {:.1f}x\n".format(
                        soc.buy_pressure, soc.volume_acceleration
                    )
                    social_context += "- Social score: {}\n".format(soc.social_score)
                    if soc.flags:
                        social_context += "- Flags: {}\n".format(", ".join(soc.flags))
                    # Pass to LLM via analysis object
                    analysis.social_context = social_context
            except Exception as e:
                logger.debug("Social check error: {}".format(e))

        # 4. LLM evaluation (with security + social context)
        if self.security and sec:
            analysis.holder_count = sec.holder_count
        logger.info("LLM evaluating {} ({})...".format(analysis.symbol, analysis.name[:20]))
        verdict = self.llm.evaluate(analysis)

        if verdict and not verdict.should_buy:
            logger.info("LLM SKIP: {} — {}".format(analysis.symbol, verdict.reasoning))
            return False

        # Determine trade amount
        amount_usd = self.config.buy_amount_eth  # reused field as USD amount
        if verdict and verdict.amount_usd > 0:
            amount_usd = min(verdict.amount_usd, self.config.buy_amount_eth)

        # 3. Execute buy
        confidence_str = ""
        if verdict:
            confidence_str = " | LLM confidence: {:.0%}".format(verdict.confidence)

        logger.info("Executing BUY: {} ({}) | ${:.8f}{}".format(
            analysis.symbol, analysis.name[:20], analysis.price_usd, confidence_str
        ))

        result = await self.executor.buy_token(
            contract_address,
            amount_eth=amount_usd,
            symbol=analysis.symbol,
        )

        if result.get("status") in ("success", "dry-run"):
            # 4. Record position
            now = datetime.utcnow()
            # Calculate exit levels (0 = disabled)
            tp_price = 0.0
            sl_price = 0.0
            exit_time = now + timedelta(days=365)  # effectively never

            if self.config.take_profit_pct > 0:
                tp_price = analysis.price_usd * (1 + self.config.take_profit_pct / 100)
            if self.config.stop_loss_pct > 0:
                sl_price = analysis.price_usd * (1 - self.config.stop_loss_pct / 100)
            if self.config.time_exit_minutes > 0:
                exit_time = now + timedelta(minutes=self.config.time_exit_minutes)

            position = Position(
                token_address=contract_address,
                symbol=analysis.symbol,
                entry_price=analysis.price_usd,
                amount_usd=amount_usd,
                entry_time=now,
                take_profit_price=tp_price,
                stop_loss_price=sl_price,
                exit_deadline=exit_time,
                source=source,
            )
            self.positions[addr_lower] = position

            # 5. Record in portfolio
            self.portfolio.record_entry(
                token_address=contract_address,
                symbol=analysis.symbol,
                amount_eth=amount_usd,
                entry_price=analysis.price_usd,
                tx_result=result,
                source=source,
            )

            exit_info = []
            if tp_price > 0:
                exit_info.append("TP: ${:.8f}".format(tp_price))
            if sl_price > 0:
                exit_info.append("SL: ${:.8f}".format(sl_price))
            if self.config.time_exit_minutes > 0:
                exit_info.append("Exit: {}min".format(self.config.time_exit_minutes))
            if not exit_info:
                exit_info.append("Manual exit")

            logger.success("Position opened: {} @ ${:.8f} | {}".format(
                analysis.symbol, analysis.price_usd, " | ".join(exit_info),
            ))
            return True
        else:
            logger.error("Buy failed: {}".format(result))
            return False

    async def check_exits(self):
        # type: () -> int
        """Check all open positions for exit conditions. Returns number of exits."""
        exits = 0
        open_positions = [
            (addr, pos) for addr, pos in self.positions.items()
            if pos.status == "open"
        ]

        if not open_positions:
            return 0

        for addr, pos in open_positions:
            # Try Uniswap API first for price (deeper integration), fall back to DexScreener
            current_price = None
            if hasattr(self.executor, 'get_token_price_usd'):
                try:
                    current_price = await self.executor.get_token_price_usd(addr)
                except Exception:
                    pass

            if not current_price:
                analysis = await self.analyzer.analyze(addr)
                if not analysis or analysis.price_usd == 0:
                    continue
                current_price = analysis.price_usd
            now = datetime.utcnow()

            should_exit = False
            reason = ""

            if pos.take_profit_price > 0 and current_price >= pos.take_profit_price:
                should_exit = True
                pnl = (current_price / pos.entry_price - 1) * 100
                reason = "TAKE-PROFIT +{:.1f}%".format(pnl)
            elif pos.stop_loss_price > 0 and current_price <= pos.stop_loss_price:
                should_exit = True
                pnl = (current_price / pos.entry_price - 1) * 100
                reason = "STOP-LOSS {:.1f}%".format(pnl)
            elif now >= pos.exit_deadline:
                should_exit = True
                pnl = (current_price / pos.entry_price - 1) * 100
                reason = "TIME-EXIT {:.1f}% after {}min".format(
                    pnl, self.config.time_exit_minutes
                )

            if should_exit:
                logger.info("EXIT: {} | {} | ${:.8f} -> ${:.8f}".format(
                    pos.symbol, reason, pos.entry_price, current_price
                ))

                result = await self.executor.sell_token(addr, symbol=pos.symbol)
                pos.status = "closed"

                self.portfolio.record_exit(
                    token_address=addr,
                    exit_price=current_price,
                    reason=reason,
                    tx_result=result,
                )
                exits += 1

        return exits

    def get_status(self):
        # type: () -> dict
        open_positions = [p for p in self.positions.values() if p.status == "open"]
        return {
            "open_positions": len(open_positions),
            "total_processed": len(self.positions),
            "positions": [
                {
                    "symbol": p.symbol,
                    "entry_price": p.entry_price,
                    "amount_usd": p.amount_usd,
                    "age_minutes": (datetime.utcnow() - p.entry_time).total_seconds() / 60,
                }
                for p in open_positions
            ],
        }
