# Sentinel

**Autonomous AI trading agent for Base — verify before you trust**

> Every hour, hundreds of tokens deploy on Base. 99% are scams: honeypots, hidden taxes, rug pulls. Sentinel is an AI agent that doesn't trust — it verifies. Three independent security layers filter signal from noise before any trade executes on-chain.

## The Problem

Crypto agents that trade autonomously face a trust problem:

- **DexScreener socials** can be faked — anyone can add a Twitter link
- **Liquidity** can be pulled — deployer adds $50K, waits for buys, removes it
- **Smart contracts** can be traps — honeypots let you buy but not sell
- **Existing bots** either buy everything (lose money) or need manual research (too slow)

There's no agent that autonomously verifies token safety at the speed of on-chain. Sentinel closes this gap.

## The Solution

Sentinel doesn't trust any single data source. It cross-references three independent verification layers before risking capital:

```
Telegram (deployment feeds: @OttoBASEDeployments, @BasePairs)
        │
        ▼
┌──────────────────────┐
│  Contract Detection   │  Regex: extracts 0x... from messages
│  + Watchlist          │  Polls DexScreener every 30s until liquidity appears
└───────────┬──────────┘
            │  Token has liquidity > $5K?
            ▼
┌──────────────────────┐
│  LAYER 1: DexScreener │  Quantitative analysis (15+ metrics):
│  Market Data          │  Liquidity, volume (1h/24h), V/L ratio,
│                       │  momentum (1h/6h/24h), buy/sell ratio,
│                       │  pair age, FDV, social presence
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  LAYER 2: GoPlus      │  Security audit (FREE API):
│  Contract Security    │  Honeypot? Hidden tax? Proxy contract?
│                       │  Hidden owner? Mintable? Blacklist?
│                       │  ❌ Honeypot → REJECT (save LLM cost)
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  LAYER 3: LLM         │  AI reasoning (Claude / GPT / local):
│  Intelligence         │  Evaluates all data + past trade history
│                       │  → Confidence score + reasoning
│                       │  ❌ < 60% confidence → SKIP
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  Uniswap API          │  Quote + optimal routing on Base
│  + Bankr Wallet       │  Gas-free execution, no private keys
└───────────┬──────────┘
            │
            ▼
┌──────────────────────┐
│  Portfolio Tracker     │  trades.json: full P&L history
│  + Self-Learning      │  Past trades fed back to LLM
└──────────────────────┘
```

## Two Modes, Two Trust Levels

Sentinel lets the human choose how much to trust the agent:

### Scanner Mode (default) — verify everything
```bash
python src/main.py --dry-run          # simulated
python src/main.py --live             # real trades
```
Watches Base deployment channels → waits for liquidity → security audit → LLM evaluation → trade only if everything passes. Autonomous 24/7.

### Sniper Mode — speed over safety
```bash
python src/main.py --dry-run --sniper  # simulated
python src/main.py --live --sniper     # real trades
```
For when you know a specific token is launching in a specific channel. Buys instantly on detection, runs security checks **after** purchase as alerts. You can profit on risky tokens and get warned if something's wrong.

```
Scanner:  Detect → Verify → Verify → Verify → Buy     (safe, slow)
Sniper:   Detect → BUY → Alert if dangerous            (fast, risky)
```

The human decides the trust level. The agent executes transparently either way.

## Live Trade Proof

Real trades executed on Base mainnet:

| Action | Token | Amount | Tx Hash |
|--------|-------|--------|---------|
| BUY | DEGEN | $1.00 → 1,376.81 DEGEN | [0x324aca...](https://basescan.org/tx/0x324aca2bc2fb0a0aa79680888ffcfb4f6da48607ac2feaf7d7505160ab17d818) |
| SELL | DEGEN | 1,376.81 DEGEN → $0.98 USDC | [0xf46a57...](https://basescan.org/tx/0xf46a57f77aad7ec90d4be42021cbee73f153075742de9b67716de4e3dc8ee078) |

Wallet: [`0xcd5c239cd4717778d326bd25781bf1b26825927a`](https://basescan.org/address/0xcd5c239cd4717778d326bd25781bf1b26825927a)

## What Makes This an Agent (Not a Bot)

| Trading Bot | Sentinel |
|------------|----------|
| Hardcoded rules | LLM reasons about each token with 15+ data points |
| Trusts one data source | Cross-references DexScreener + GoPlus + LLM |
| Same logic forever | Self-learning: feeds past trade P&L back to LLM |
| Fixed strategy | User configures trust level, exit strategy, position sizing |
| One LLM provider | Multi-provider fallback: Bankr → Anthropic → OpenAI → Claude CLI → Ollama |

## Quick Start

```bash
git clone https://github.com/tearful-saw/sentinel.git
cd sentinel
pip install -r requirements.txt
cp .env.example .env       # Add your API keys
```

```bash
# Demo — no Telegram or wallet needed, runs sample tokens through full pipeline
python src/main.py --demo

# Scanner — real Telegram monitoring, simulated trades
python src/main.py --dry-run

# Sniper — instant buy mode, simulated
python src/main.py --dry-run --sniper

# Live trading
python src/main.py --live

# Skip LLM (faster, rule-based only)
python src/main.py --demo --no-llm
```

## Exit Strategy (User-Configurable)

All exit rules are **optional** — set to `0` to disable. You control the strategy:

```yaml
# config.yaml
trading:
  take_profit_pct: 0       # 0 = manual exit only
  stop_loss_pct: 0         # 0 = no stop loss
  time_exit_minutes: 0     # 0 = hold indefinitely
```

Presets:
```yaml
# Scalper:  TP 20%, SL 10%, exit after 30min
# Diamond:  all zeros — you decide when to sell
# Quick:    TP 50%, SL 15%, exit after 10min
```

## LLM Evaluation — What Claude Sees

Each token evaluation includes 15+ data points:

```
TOKEN: MOLTSCORE | Chain: Base | Price: $0.00034
LIQUIDITY: $38,606 pool | Volume 1h: $5,200 | V/L ratio: 0.13
MOMENTUM: +12.3% 1h | +8.1% 6h | N/A 24h (new)
ACTIVITY: 45 buys / 12 sells = 3.8x | Pair age: 2 minutes
SOCIAL: Website: No | Twitter: No | Telegram: No
SECURITY: GoPlus OK | 0% tax | not honeypot | 3 holders
PAST TRADES: "Last similar token (low social, new pair): -80%"
→ LLM verdict: SKIP (confidence: 45%) — "No social presence,
   very new with unverified contract, similar to past loss"
```

The LLM doesn't just check numbers — it **reasons** about patterns and learns from mistakes.

## Security Layer (GoPlus)

Free on-chain security audit before every Scanner trade:

| Check | What it catches |
|-------|----------------|
| Honeypot detection | Token that can't be sold |
| Sell tax analysis | Hidden 50%+ tax on sells |
| Hidden owner | Owner can change balances |
| Proxy contract | Code can be changed after deploy |
| Mint function | Infinite token creation |
| Transfer pause | Trading can be frozen |
| Holder concentration | Top 10 wallets hold 90%+ |

Honeypots are rejected **before** LLM evaluation — no point spending inference on a token you can't sell.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Signal Detection | Telethon (MTProto) | Real-time Telegram channel monitoring |
| Contract Detection | Regex engine | Extract 0x... addresses from text |
| Pair Discovery | DexScreener API | Liquidity, volume, momentum, social data |
| Security Audit | GoPlus API (free) | Honeypot, tax, owner, proxy detection |
| AI Evaluation | Multi-provider LLM | Intelligent buy/skip with self-learning |
| Swap Routing | Uniswap Trading API | Optimal quotes and routing on Base |
| Trade Execution | Bankr API | Gas-free swaps, custodial wallet |
| Price Monitoring | Uniswap API | Position exit price tracking |
| P&L Tracking | JSON trade journal | Full audit trail |

### LLM Provider Chain (automatic fallback)
```
Bankr LLM Gateway → Anthropic API → OpenAI API → Claude CLI → Ollama
     (self-funded)    (user key)      (user key)    (harness)    (local/free)
```
Configure via env vars. First available provider wins.

## Project Structure

```
sentinel/
├── README.md                          # This file
├── SKILL.md                           # Agent skill file for integration
├── requirements.txt
├── .env.example                       # All supported env vars documented
├── config/config.example.yaml         # Strategy presets with examples
├── src/
│   ├── main.py                        # Entry point (--demo/--dry-run/--live/--sniper)
│   ├── config.py                      # YAML + env config loader
│   ├── demo_signals.py                # Demo mode token feeder
│   ├── detectors/
│   │   └── contract_detector.py       # EVM + Solana address regex
│   ├── monitors/
│   │   ├── telegram_monitor.py        # Real-time Telegram watcher
│   │   └── pair_scanner.py            # Watchlist + DexScreener polling
│   ├── analysis/
│   │   ├── token_analyzer.py          # DexScreener: 15+ metrics
│   │   ├── security_checker.py        # GoPlus: honeypot/rug detection
│   │   └── llm_evaluator.py           # Multi-provider LLM evaluation
│   ├── strategy/
│   │   └── signal_strategy.py         # Pipeline orchestration + exits
│   ├── traders/
│   │   ├── uniswap_executor.py        # Uniswap API: quotes + routing
│   │   └── onchain_executor.py        # Bankr API: wallet + execution
│   └── monitoring/
│       └── portfolio.py               # P&L tracking + trade history
└── data/trades.json                   # Trade journal (auto-generated)
```

## Hackathon Tracks

### Autonomous Trading Agent — Base ($5K)
*"Novel strategies, proven profitability"*

Sentinel's novelty: three-layer verification (DexScreener + GoPlus + LLM) replaces blind sniping. The agent doesn't just trade — it reasons about whether to trade, then learns from the outcome. Real mainnet execution with tx hashes on BaseScan.

### Agentic Finance — Uniswap ($5K)
*"Deeper into the Uniswap stack = more we notice"*

Uniswap Trading API integration for both trade execution and price monitoring:
- Entry: `POST /v1/quote` for optimal routing across v3/v4 pools
- Exit: Uniswap price quotes for position monitoring and TP/SL triggers
- Real API key, real TxIDs on mainnet

### Best Bankr LLM Gateway Use — Bankr ($5K)
*"Self-sustaining economics"*

Sentinel uses Bankr for wallet management and trade execution. LLM evaluator supports Bankr LLM Gateway as primary inference provider — agent pays for its own reasoning from trading activity. Multi-provider fallback ensures the agent always has intelligence available.

### Synthesis Open Track ($28K)
*"Agents that trust"*

Sentinel directly addresses the hackathon's core theme: **how do you trust an agent that moves money?**

- **Agents that pay**: Every transaction is on-chain, verifiable on BaseScan. Human controls position size, exit strategy, and max positions via config.
- **Agents that trust**: Sentinel doesn't trust — it verifies. Three independent layers (market data, contract security, AI reasoning) cross-reference before any trade. DexScreener socials can be faked, so GoPlus checks the actual contract code.
- **Agents that cooperate**: Published as a SKILL.md — other agents can use Sentinel's analysis pipeline as a tool.
- **Agents that keep secrets**: No private keys exposed (Bankr custody), API keys in local .env only, signal sources not transmitted externally.

## License

MIT
