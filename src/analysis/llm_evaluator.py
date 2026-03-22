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
    """
    Evaluates tokens using LLM with multi-provider support and self-learning.

    Provider priority (tries in order, falls back on failure):
    1. Bankr LLM Gateway (self-funded, agent pays for own inference)
    2. OpenAI-compatible API (user's own key — OpenAI, Anthropic, local)
    3. Claude CLI (claude-code harness)

    Configure via environment variables:
      BANKR_API_KEY          → Bankr LLM Gateway (supports Claude, GPT, Gemini)
      OPENAI_API_KEY         → OpenAI API (GPT models)
      OPENAI_API_BASE        → Custom endpoint (e.g. local Ollama, Together, Groq)
      ANTHROPIC_API_KEY      → Anthropic API (Claude models)
    """

    def __init__(self, model="sonnet", enabled=True, portfolio=None, bankr_llm_key=""):
        self.model = model
        self.enabled = enabled
        self.portfolio = portfolio
        self.bankr_llm_key = bankr_llm_key

        # Load optional provider keys from env
        import os
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    def _get_past_trades_section(self):
        # type: () -> str
        """Format recent closed trades for LLM context."""
        if not self.portfolio:
            return ""

        closed = [t for t in self.portfolio.trades if t.get("status") == "closed"]
        if not closed:
            return ""

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

    def _call_openai_compatible(self, prompt, api_url, api_key, model):
        # type: (str, str, str, str) -> Optional[str]
        """Call any OpenAI-compatible API (OpenAI, Bankr, Groq, Together, Ollama, etc.)."""
        import requests
        try:
            resp = requests.post(
                "{}/chat/completions".format(api_url.rstrip("/")),
                headers={
                    "Authorization": "Bearer {}".format(api_key) if not api_url.startswith("https://llm.bankr") else "",
                    "X-API-Key": api_key if api_url.startswith("https://llm.bankr") else "",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return None
        except Exception:
            return None

    def _call_anthropic(self, prompt, api_key, model):
        # type: (str, str, str) -> Optional[str]
        """Call Anthropic API directly."""
        import requests
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", [{}])
                if content:
                    return content[0].get("text", "")
            return None
        except Exception:
            return None

    def _call_claude_cli(self, prompt):
        # type: (str) -> Optional[str]
        """Call Claude via local CLI (claude-code harness)."""
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", self.model, "--max-turns", "1"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout.strip() if result.stdout else None
        except FileNotFoundError:
            return None

    def _call_llm(self, prompt):
        # type: (str) -> Optional[str]
        """Try providers in priority order. First success wins."""

        # 1. Bankr LLM Gateway (self-funded inference)
        if self.bankr_llm_key:
            result = self._call_openai_compatible(
                prompt, "https://llm.bankr.bot/v1", self.bankr_llm_key, self.anthropic_model
            )
            if result:
                logger.debug("LLM provider: Bankr Gateway (self-funded)")
                return result

        # 2. Anthropic API (user's own key)
        if self.anthropic_key:
            result = self._call_anthropic(prompt, self.anthropic_key, self.anthropic_model)
            if result:
                logger.debug("LLM provider: Anthropic API")
                return result

        # 3. OpenAI-compatible API (OpenAI, Groq, Together, Ollama, etc.)
        if self.openai_key:
            result = self._call_openai_compatible(
                prompt, self.openai_base, self.openai_key, self.openai_model
            )
            if result:
                logger.debug("LLM provider: OpenAI-compatible ({})".format(self.openai_base))
                return result

        # 4. Claude CLI (always available in claude-code)
        result = self._call_claude_cli(prompt)
        if result:
            logger.debug("LLM provider: Claude CLI")
            return result

        return None

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
            response = self._call_llm(prompt)

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
