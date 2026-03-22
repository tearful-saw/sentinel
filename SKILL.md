# Sentinel — Autonomous Alpha Signal Trading Agent

> Base URL: `https://raw.githubusercontent.com/tearful-saw/sentinel/master`

You are integrating **Sentinel**, an autonomous AI trading agent for Base chain. Sentinel monitors new token deployments, analyzes them through multiple layers (DexScreener + GoPlus Security + LLM evaluation), and executes trades via Uniswap + Bankr.

---

## What Sentinel Does

Sentinel is a signal-to-execution pipeline for trading new tokens on Base:

1. **Detect** — Monitors Telegram channels for new token deployments on Base
2. **Watch** — Adds tokens to a watchlist, polls DexScreener until liquidity appears (>$5K)
3. **Secure** — Checks GoPlus Security API: honeypot detection, sell tax, hidden owner, proxy contract
4. **Evaluate** — Claude LLM analyzes 15+ metrics: liquidity, volume, momentum, buy/sell ratio, pair age, FDV, social presence, past trade history
5. **Execute** — Gets Uniswap V3 quote for optimal routing, executes via Bankr (gas-free)
6. **Track** — Records all trades in `trades.json` with P&L, feeds history back to LLM (self-learning)

---

## Quick Setup

### Prerequisites
- Python 3.8+
- Telegram API credentials ([my.telegram.org](https://my.telegram.org))
- Bankr API key ([bankr.bot](https://bankr.bot)) — free, provides wallet + gas-free execution
- Uniswap API key ([developers.uniswap.org](https://developers.uniswap.org)) — free

### Install

```bash
git clone https://github.com/tearful-saw/sentinel.git
cd sentinel
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

### Configure `.env`

```
TELEGRAM_API_ID=your_id
TELEGRAM_API_HASH=your_hash
TELEGRAM_PHONE=+1234567890
BANKR_API_KEY=bk_your_key
UNISWAP_API_KEY=your_key
```

### Configure `config/config.yaml`

```yaml
sources:
  telegram:
    - "OttoBASEDeployments"   # Base deployment feed
    - "BasePairs"             # New pairs on Base

trading:
  buy_amount_eth: 0.01        # Position size
  min_liquidity_usd: 5000     # Minimum pool liquidity
  take_profit_pct: 0          # 0 = manual exit
  stop_loss_pct: 0            # 0 = no stop loss
  time_exit_minutes: 0        # 0 = hold indefinitely
  max_positions: 5
```

---

## Commands

### Demo Mode (no Telegram, no wallet needed)
```bash
python src/main.py --demo
```
Runs sample Base tokens through the full pipeline: DexScreener → GoPlus → LLM → dry-run trade.

### Scanner Mode (autonomous)
```bash
python src/main.py --dry-run          # Simulated trades
python src/main.py --live             # Real trades via Bankr
```
Watches deployment channels → polls for liquidity → security check → LLM evaluation → trade.

### Sniper Mode (human-directed)
```bash
python src/main.py --dry-run --sniper  # Simulated
python src/main.py --live --sniper     # Real trades
```
Monitors specific alpha channels, instantly buys when contract address appears.

### Flags
- `--no-llm` — Skip Claude evaluation (faster, rule-based only)
- `--sniper` — Switch to sniper mode (instant buy vs scanner watchlist)

---

## Architecture

```
Telegram (deployment feeds)
       │
       ▼
  Contract Detection (regex: 0x...)
       │
       ▼
  Watchlist + DexScreener Polling (30s intervals)
  "Does this token have liquidity > $5K?"
       │
       ▼
  GoPlus Security Check (FREE API)
  "Is this a honeypot? Hidden tax? Proxy?"
       │
       ▼
  Claude LLM Evaluation
  "15+ metrics → confidence score → buy/skip"
  "Self-learning from past trade history"
       │
       ▼
  Uniswap API (quote + routing)
  Bankr API (gas-free execution on Base)
       │
       ▼
  Portfolio Tracker (trades.json + P&L)
```

---

## APIs Used

| API | Purpose | Cost |
|-----|---------|------|
| DexScreener | Token liquidity, volume, momentum, socials | Free |
| GoPlus Security | Honeypot detection, rug analysis | Free |
| Uniswap Trading API | Swap quotes, optimal routing | Free |
| Bankr | Wallet, gas-free execution on Base | Free |
| Claude (via CLI) | Intelligent token evaluation | Via agent harness |

---

## Trade History

All trades are saved to `data/trades.json`:
```json
{
  "token": "0x4ed4E862...",
  "symbol": "DEGEN",
  "action": "BUY",
  "entry_price": 0.000726,
  "tx": {"tx_hash": "0x324aca..."},
  "status": "closed",
  "exit_price": 0.000712,
  "pnl_pct": -2.0
}
```

---

## For Agent Developers

Sentinel's components are modular and can be used independently:

```python
from analysis.token_analyzer import TokenAnalyzer
from analysis.security_checker import SecurityChecker
from analysis.llm_evaluator import LLMEvaluator

# Analyze any token
analyzer = TokenAnalyzer(min_liquidity_usd=5000)
result = await analyzer.analyze("0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed")
# → AnalysisResult(symbol="DEGEN", liquidity=418000, volume_24h=54000, ...)

# Security check
checker = SecurityChecker()
security = await checker.check("0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed")
# → SecurityResult(is_safe=True, is_honeypot=False, sell_tax=0, ...)

# LLM evaluation
evaluator = LLMEvaluator(model="sonnet")
verdict = evaluator.evaluate(result)
# → LLMVerdict(should_buy=False, confidence=0.55, reasoning="...")
```
