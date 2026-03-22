"""
LLM-based token evaluator.
Uses Claude CLI to assess whether a token is worth trading,
based on DexScreener data and market context.
"""

import subprocess
import json
import re
from typing import Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class LLMVerdict:
    should_buy: bool
    confidence: float       # 0.0 - 1.0
    reasoning: str
    amount_usd: float       # suggested position size


EVALUATION_PROMPT = """You are a crypto trading analyst. Evaluate this token for a quick trade on Base chain.

TOKEN DATA:
- Symbol: {symbol}
- Name: {name}
- Contract: {address}
- Chain: {chain}
- Price: ${price:.10f}
- FDV: ${fdv:,.0f}

LIQUIDITY & VOLUME:
- Pool liquidity: ${liquidity:,.0f}
- Volume 1h: ${volume_1h:,.0f}
- Volume 24h: ${volume_24h:,.0f}
- Volume/Liquidity ratio: {vol_liq_ratio:.2f}

MOMENTUM:
- Price change 1h: {price_change_1h:+.1f}%
- Price change 6h: {price_change_6h:+.1f}%
- Price change 24h: {price_change_24h:+.1f}%

ACTIVITY:
- Buys last hour: {buys_1h}
- Sells last hour: {sells_1h}
- Buy/Sell ratio: {buy_sell_ratio}
- Pair age: {pair_age}

SOCIAL PRESENCE:
- Website: {has_website}
- Twitter: {has_twitter}
- Telegram: {has_telegram}
{past_trades_section}
DECISION FRAMEWORK:
- BUY signals: high volume relative to liquidity (>0.5), more buys than sells, positive momentum, social presence, pair < 24h old with growing volume
- SKIP signals: volume/liquidity < 0.1, more sells than buys, no social presence, suspicious name, pair very old with declining volume, FDV > $50M (too late)
- We trade small positions ($1-5) on Base via Uniswap
- Be conservative. Only recommend if confidence > 0.6
- Learn from past trades: avoid patterns that led to losses

Respond ONLY with this JSON (no markdown, no extra text):
{{"should_buy": true/false, "confidence": 0.0-1.0, "reasoning": "one sentence", "amount_usd": 1-5}}"""


class LLMEvaluator:
    """Evaluates tokens using Claude CLI with learning from past trades."""

    def __init__(self, model="sonnet", enabled=True, portfolio=None):
        self.model = model
        self.enabled = enabled
        self.portfolio = portfolio  # for learning from past trades

    def _get_past_trades_section(self):
        # type: () -> str
        """Format recent closed trades for LLM context."""
        if not self.portfolio:
            return ""

        closed = [t for t in self.portfolio.trades if t.get("status") == "closed"]
        if not closed:
            return ""

        # Last 5 closed trades
        recent = closed[-5:]
        lines = ["\nYOUR PAST TRADES (learn from these):"]
        for t in recent:
            pnl = t.get("pnl_pct", 0)
            result = "+{:.0f}%".format(pnl) if pnl > 0 else "{:.0f}%".format(pnl)
            reason = t.get("exit_reason", "")
            lines.append("- {} ({}): {} {}".format(
                t.get("symbol", "?"), t.get("source", ""), result, reason
            ))

        return "\n".join(lines) + "\n"

    def evaluate(self, analysis_result):
        # type: (any) -> Optional[LLMVerdict]
        """Ask Claude to evaluate a token based on DexScreener data + past trade history."""
        if not self.enabled:
            return LLMVerdict(
                should_buy=True, confidence=0.5,
                reasoning="LLM evaluation disabled, passing through",
                amount_usd=2.0,
            )

        if not analysis_result or analysis_result.price_usd == 0:
            return LLMVerdict(
                should_buy=False, confidence=0.0,
                reasoning="No price data available",
                amount_usd=0,
            )

        vol_liq = analysis_result.volume_24h / max(analysis_result.liquidity_usd, 1)

        # Format derived fields
        buys = analysis_result.buys_1h
        sells = analysis_result.sells_1h
        if sells > 0:
            buy_sell_ratio = "{:.1f}x".format(buys / sells)
        elif buys > 0:
            buy_sell_ratio = "{}x (no sells)".format(buys)
        else:
            buy_sell_ratio = "no activity"

        age_h = analysis_result.pair_age_hours
        if age_h < 1:
            pair_age = "{:.0f} minutes".format(age_h * 60)
        elif age_h < 24:
            pair_age = "{:.1f} hours".format(age_h)
        else:
            pair_age = "{:.0f} days".format(age_h / 24)

        prompt = EVALUATION_PROMPT.format(
            symbol=analysis_result.symbol,
            name=analysis_result.name,
            address=analysis_result.address,
            chain=analysis_result.chain,
            liquidity=analysis_result.liquidity_usd,
            volume_24h=analysis_result.volume_24h,
            volume_1h=analysis_result.volume_1h,
            price=analysis_result.price_usd,
            vol_liq_ratio=vol_liq,
            price_change_1h=analysis_result.price_change_1h,
            price_change_6h=analysis_result.price_change_6h,
            price_change_24h=analysis_result.price_change_24h,
            buys_1h=buys,
            sells_1h=sells,
            buy_sell_ratio=buy_sell_ratio,
            pair_age=pair_age,
            fdv=analysis_result.fdv,
            has_website="Yes" if analysis_result.has_website else "No",
            has_twitter="Yes" if analysis_result.has_twitter else "No",
            has_telegram="Yes" if analysis_result.has_telegram else "No",
            past_trades_section=self._get_past_trades_section(),
        )

        try:
            result = subprocess.run(
                ["claude", "-p", "--model", self.model, "--max-turns", "1"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=30,
            )

            response = result.stdout.strip()
            if not response:
                logger.warning("LLM returned empty response")
                return None

            # Strip markdown code fences if present
            response = re.sub(r'^```(?:json)?\s*', '', response)
            response = re.sub(r'\s*```$', '', response)

            # Try to extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if not json_match:
                logger.warning("LLM response not JSON: {}".format(response[:100]))
                return None

            data = json.loads(json_match.group())

            verdict = LLMVerdict(
                should_buy=bool(data.get("should_buy", False)),
                confidence=float(data.get("confidence", 0)),
                reasoning=str(data.get("reasoning", "")),
                amount_usd=float(data.get("amount_usd", 2)),
            )

            emoji = "BUY" if verdict.should_buy else "SKIP"
            logger.info("LLM verdict: {} (confidence: {:.0%}) — {}".format(
                emoji, verdict.confidence, verdict.reasoning
            ))

            return verdict

        except subprocess.TimeoutExpired:
            logger.warning("LLM evaluation timed out")
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("LLM response parse error: {}".format(e))
            return None
        except FileNotFoundError:
            logger.warning("Claude CLI not found, skipping LLM evaluation")
            self.enabled = False
            return None
