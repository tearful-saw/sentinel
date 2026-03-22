# Sentinel

**Autonomous AI trading agent for Base**

> Detects token signals from Telegram alpha channels, evaluates them with Claude LLM, and executes trades on Base via Bankr — fully autonomous, self-funding, no human in the loop.

## The Problem

Alpha signals in crypto flow through Telegram channels seconds before price moves. A human reading a message, checking DexScreener, evaluating the token, opening a DEX, and swapping takes 60-120 seconds. By then, the opportunity is gone.

99% of newly deployed tokens are scams or rugs. Blindly buying every signal loses money. You need an intelligent filter — an agent that can reason about token data and make autonomous buy/skip decisions.

## The Solution

Sentinel is a self-sustaining AI agent that:

```
Telegram Alpha Channel (Cielo/GMGN filtered alerts)
        │
        ▼
┌─────────────────────┐
│  Signal Monitor      │  Telethon (MTProto) — real-time, < 100ms
│  Contract Detection  │  Regex: EVM 0x... + Solana + DexScreener URLs
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Token Analyzer      │  DexScreener API — liquidity, volume, chain
│  Quantitative gate   │  Filter: $5K+ liquidity, Base chain, not stablecoin
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  LLM Evaluator       │  Claude AI reasons about token data:
│  Qualitative gate    │  "Volume/liquidity ratio 2.3x, 340 holders,
│                      │   LP locked → BUY confidence: 0.85"
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Bankr Executor      │  Natural language API on Base:
│  On-chain swap       │  POST /agent/prompt "Buy $5 of 0x532f... on Base"
│  Gas-free execution  │  Wallet managed by Bankr, no private keys
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Portfolio Tracker   │  trades.json — full P&L history
│  Auto-exit manager   │  Take-profit +50% | Stop-loss -30% | Time exit 1hr
└─────────────────────┘
```

## What Makes This an Agent (Not Just a Bot)

| Bot | Agent (Sentinel) |
|-----|-----------------|
| Follows hardcoded rules | Claude LLM reasons about each signal |
| Buy everything that passes filter | Evaluates confidence score, adjusts position size |
| No context awareness | Understands market sentiment from message text |
| Static thresholds | Adapts reasoning to token specifics |

The LLM evaluator receives quantitative data (liquidity, volume, V/L ratio) and returns a structured decision with confidence score and reasoning. This is not pattern matching — it's autonomous decision-making.

## Why Base + Bankr?

- **Sub-cent fees**: Micro-position strategies are viable
- **2-second blocks**: Fast confirmation
- **Bankr gas sponsorship**: Agent pays zero gas fees
- **No private key management**: Bankr provides custodial wallet
- **Natural language execution**: `"Buy $5 of TOKEN on Base"` — that's it
- **Self-funding potential**: Launch token → trading fees → pay for inference

## Quick Start

```bash
cd sentinel
pip install -r requirements.txt

cp .env.example .env   # Add Telegram + Bankr credentials

# Demo mode — no Telegram needed, shows full pipeline
python src/main.py --demo

# Dry-run — real Telegram monitoring, simulated trades
python src/main.py --dry-run

# Live — real everything via Bankr
python src/main.py --live

# Without LLM evaluation (faster, rule-based only)
python src/main.py --demo --no-llm
```

## Demo Output

```
12:34:56 | INFO     | ============================================================
12:34:56 | INFO     |   SENTINEL — Autonomous Alpha Signal Trading Agent
12:34:56 | INFO     |   Mode: DEMO | LLM: Claude
12:34:56 | INFO     |   Execution: Bankr API (natural language trading)
12:34:56 | INFO     | ============================================================
12:34:57 | INFO     | Analyzing 0x532f27101965dd1644...
12:34:57 | SUCCESS  | PASS: BRETT | Liq: $1,271,076 | Vol 24h: $2,397
12:34:58 | INFO     | LLM evaluating BRETT (Brett)...
12:34:59 | INFO     | LLM verdict: BUY (confidence: 78%) — High liquidity, established Base memecoin
12:34:59 | INFO     | [DRY-RUN] Would buy $3 of BRETT on Base
12:34:59 | SUCCESS  | Position opened: BRETT @ $0.00657700
12:35:01 | INFO     | Analyzing 0x833589fCD6eDb6E08f...
12:35:01 | INFO     | REJECT: USDC — Blacklisted stablecoin
```

## Strategy & Risk Management

### Entry Pipeline
1. Contract address detected from monitored alpha channel
2. DexScreener check: liquidity > $5K, Base chain pool, not stablecoin
3. Claude LLM evaluates: token data → confidence score → position size
4. Only buy if LLM confidence > 60%

### Exit Strategy (User-Configurable)

All exit rules are **optional** — set any value to `0` to disable it. You choose your own strategy:

| Setting | Default | Description |
|---------|---------|-------------|
| `take_profit_pct` | `0` (off) | Auto-sell when price rises X% from entry |
| `stop_loss_pct` | `0` (off) | Auto-sell when price drops X% from entry |
| `time_exit_minutes` | `0` (off) | Auto-sell after X minutes |

**Preset examples in `config.yaml`:**

```yaml
# Conservative scalper — quick in and out
take_profit_pct: 20
stop_loss_pct: 10
time_exit_minutes: 30

# Diamond hands — hold until you decide
take_profit_pct: 0
stop_loss_pct: 0
time_exit_minutes: 0

# Quick flip — aggressive short-term
take_profit_pct: 50
stop_loss_pct: 15
time_exit_minutes: 10
```

### Safety
- **Dry-run mode**: Full pipeline simulation, zero risk
- **LLM gating**: Claude must approve with confidence > 0.6
- **Configurable exits**: User controls TP/SL/time, or disables all for manual management
- **Position limits**: Max concurrent positions (configurable)
- **Blacklist**: Known stablecoins/wrappers never traded
- **Deduplication**: Won't buy same token twice
- **Full audit trail**: Every decision in trades.json

## Project Structure

```
sentinel/
├── README.md
├── requirements.txt
├── .env.example
├── config/config.yaml
├── src/
│   ├── main.py                  # Entry point (--dry-run/--demo/--live)
│   ├── config.py                # YAML + env config loader
│   ├── demo_signals.py          # Demo mode signal feeder
│   ├── detectors/
│   │   └── contract_detector.py # EVM + Solana address detection
│   ├── monitors/
│   │   └── telegram_monitor.py  # Real-time Telegram watcher
│   ├── analysis/
│   │   ├── token_analyzer.py    # DexScreener liquidity analysis
│   │   └── llm_evaluator.py     # Claude LLM token evaluation
│   ├── strategy/
│   │   └── signal_strategy.py   # Buy/sell decision engine
│   ├── traders/
│   │   └── onchain_executor.py  # Bankr API trade execution
│   └── monitoring/
│       └── portfolio.py         # P&L tracking & trade history
└── data/trades.json             # Trade history (auto-generated)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Signal Monitoring | Telethon (Telegram MTProto) |
| Contract Detection | Regex + DexScreener URL parsing |
| Token Analysis | DexScreener REST API |
| LLM Evaluation | Claude (via CLI or Bankr LLM Gateway) |
| Trade Execution | Bankr API (natural language → on-chain swap) |
| Blockchain | Base L2 (Uniswap V3 under the hood) |
| P&L Tracking | JSON trade journal |

## Hackathon Tracks

### Base Track ($5K) — "Trading agent that makes money"
Sentinel operates natively on Base, using Bankr's gas-sponsored execution for zero-fee swaps. The full pipeline — signal detection, LLM evaluation, autonomous execution — runs without human intervention.

### Uniswap Track ($10K) — "Best agentic finance integration"
Bankr executes swaps through Uniswap V3 on Base. The agent interacts with Uniswap liquidity pools for both entry and exit trades, with price discovery via DexScreener pool data.

### Bankr Track ($7,590) — "Agent that earns and pays for own inference"
Sentinel is designed for self-sustainability: Bankr wallet holds funds, Bankr API executes trades, Bankr LLM Gateway provides Claude inference. The agent can launch a token via Bankr launchpad where 57% of trading fees flow back to fund inference costs — a closed-loop autonomous economy.

### Open Track ($28.3K) — Agentic Finance Themes
- **Transparent transactions**: Every trade logged with LLM reasoning, DexScreener data, and Bankr tx response
- **Trust without registries**: Direct on-chain execution via Bankr, no intermediary approvals
- **Agent cooperation**: Modular pipeline — analyzer, evaluator, and executor operate as independent agents coordinated by strategy
- **Privacy**: Private keys managed by Bankr (never exposed), signal sources stored locally

## Self-Funding Model

```
           ┌──────────────┐
           │ Launch $SNTL  │  Bankr Token Launchpad
           │ token on Base │  (zero upfront cost)
           └──────┬───────┘
                  │
                  ▼
           1.2% fee on every swap
                  │
          ┌───────┴───────┐
          │               │
     57% to agent    43% to Bankr
          │
          ▼
   Fund LLM inference
   (via Bankr Gateway)
          │
          ▼
   Agent keeps trading
   autonomously forever
```

## License

MIT
