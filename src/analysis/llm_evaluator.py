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
- Liquidity: ${liquidity:,.0f}
- 24h Volume: ${volume:,.0f}
- Price: ${price:.10f}
- Volume/Liquidity ratio: {vol_liq_ratio:.2f}
{past_trades_section}
RULES:
- We trade small positions ($1-5) on Base via Uniswap
- Good signs: high volume relative to liquidity, growing interest, Base native
- Bad signs: very low liquidity (<$5K), no volume, suspicious name, likely rug pull
- Be conservative. Only recommend if confidence > 0.6
- Learn from past trades: avoid patterns that led to losses, repeat patterns that led to wins

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

        prompt = EVALUATION_PROMPT.format(
            symbol=analysis_result.symbol,
            name=analysis_result.name,
            address=analysis_result.address,
            chain=analysis_result.chain,
            liquidity=analysis_result.liquidity_usd,
            volume=analysis_result.volume_24h,
            price=analysis_result.price_usd,
            vol_liq_ratio=vol_liq,
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
