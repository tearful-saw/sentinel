"""
Configuration loader for Sentinel trading agent.
Reads from config/config.yaml + .env environment variables.
"""

import os
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    phone: Optional[str] = None
    session_name: str = "sentinel"


@dataclass
class WalletConfig:
    private_key: str = ""
    rpc_url: str = "https://mainnet.base.org"
    testnet_rpc_url: str = "https://sepolia.base.org"


@dataclass
class SourcesConfig:
    telegram: List[str] = field(default_factory=list)


@dataclass
class DetectionConfig:
    chains: str = "evm"
    blacklist: List[str] = field(default_factory=list)


@dataclass
class TradingConfig:
    buy_amount_eth: float = 0.01
    slippage_bps: int = 500
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 30.0
    time_exit_minutes: int = 60
    min_liquidity_usd: float = 5000.0
    max_positions: int = 5
    dry_run: bool = True


@dataclass
class ChainConfig:
    network: str = "mainnet"  # mainnet | testnet


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: Optional[str] = None


@dataclass
class Config:
    telegram: TelegramConfig
    wallet: WalletConfig
    sources: SourcesConfig
    detection: DetectionConfig
    trading: TradingConfig
    chain: ChainConfig
    logging_config: LoggingConfig


def load_config(config_path=None):
    # type: (Optional[str]) -> Config
    """Load configuration from YAML file and environment variables."""
    load_dotenv()

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"

    config_data = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}

    # Telegram config
    tg_data = config_data.get("telegram", {})
    telegram = TelegramConfig(
        api_id=int(os.getenv("TELEGRAM_API_ID", tg_data.get("api_id", 0))),
        api_hash=os.getenv("TELEGRAM_API_HASH", tg_data.get("api_hash", "")),
        phone=os.getenv("TELEGRAM_PHONE", tg_data.get("phone")),
        session_name=tg_data.get("session_name", "sentinel"),
    )

    # Wallet config
    wallet = WalletConfig(
        private_key=os.getenv("PRIVATE_KEY", ""),
        rpc_url=os.getenv("BASE_RPC_URL", "https://mainnet.base.org"),
        testnet_rpc_url=os.getenv("BASE_TESTNET_RPC_URL", "https://sepolia.base.org"),
    )

    # Sources config
    sources_data = config_data.get("sources", {})
    if isinstance(sources_data, list):
        sources = SourcesConfig(telegram=sources_data)
    else:
        sources = SourcesConfig(
            telegram=sources_data.get("telegram", []),
        )

    # Detection config
    det_data = config_data.get("detection", {})
    detection = DetectionConfig(
        chains=det_data.get("chains", "evm"),
        blacklist=det_data.get("blacklist", []),
    )

    # Trading config
    trade_data = config_data.get("trading", {})
    trading = TradingConfig(
        buy_amount_eth=trade_data.get("buy_amount_eth", 0.01),
        slippage_bps=trade_data.get("slippage_bps", 500),
        take_profit_pct=trade_data.get("take_profit_pct", 50.0),
        stop_loss_pct=trade_data.get("stop_loss_pct", 30.0),
        time_exit_minutes=trade_data.get("time_exit_minutes", 60),
        min_liquidity_usd=trade_data.get("min_liquidity_usd", 5000.0),
        max_positions=trade_data.get("max_positions", 5),
    )

    # Chain config
    chain_data = config_data.get("chain", {})
    chain = ChainConfig(
        network=chain_data.get("network", "mainnet"),
    )

    # Logging config
    log_data = config_data.get("logging", {})
    logging_config = LoggingConfig(
        level=log_data.get("level", "INFO"),
        file=log_data.get("file"),
    )

    return Config(
        telegram=telegram,
        wallet=wallet,
        sources=sources,
        detection=detection,
        trading=trading,
        chain=chain,
        logging_config=logging_config,
    )
