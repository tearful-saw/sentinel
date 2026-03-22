"""
Universal contract address detector for EVM and Solana chains.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Set


class Chain(Enum):
    EVM = "evm"
    SOLANA = "solana"


@dataclass
class DetectedContract:
    address: str
    chain: Chain
    raw_match: str


class ContractDetector:
    EVM_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
    SOLANA_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')

    BLACKLIST = {
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "0xdac17f958d2ee523a2206206994597c13d831ec7",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "0x6b175474e89094c44da98b954eedeac495271d0f",
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        "0x55d398326f99059ff775485246999027b3197955",
        "0x4200000000000000000000000000000000000006",
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    }

    SOLANA_FALSE_POSITIVES = {
        "phantom", "solana", "raydium", "jupiter", "marinade",
        "serum", "mango", "orca", "meteora", "tensor",
    }

    def __init__(self, blacklist=None):
        # type: (Optional[Set[str]]) -> None
        self.blacklist = self.BLACKLIST.copy()
        if blacklist:
            self.blacklist.update(addr.lower() for addr in blacklist)

    def detect(self, text):
        # type: (str) -> List[DetectedContract]
        if not text:
            return []

        contracts = []

        for match in self.EVM_PATTERN.finditer(text):
            address = match.group()
            if address.lower() not in self.blacklist:
                contracts.append(DetectedContract(
                    address=address,
                    chain=Chain.EVM,
                    raw_match=address
                ))

        for match in self.SOLANA_PATTERN.finditer(text):
            address = match.group()

            if address.lower() in self.SOLANA_FALSE_POSITIVES:
                continue
            if address in self.blacklist:
                continue

            start = match.start()
            if start > 0 and text[start - 1] in '/#':
                before = text[max(0, start - 20):start]
                if 'dexscreener' not in before.lower():
                    continue

            if any(c in address for c in '0OIl'):
                continue

            contracts.append(DetectedContract(
                address=address,
                chain=Chain.SOLANA,
                raw_match=address
            ))

        return contracts

    def detect_first(self, text):
        # type: (str) -> Optional[DetectedContract]
        contracts = self.detect(text)
        return contracts[0] if contracts else None

    def extract_from_dexscreener(self, text):
        # type: (str) -> Optional[DetectedContract]
        pattern = r'dexscreener\.com/(\w+)/([a-zA-Z0-9]+)'
        match = re.search(pattern, text)

        if match:
            chain_name = match.group(1).lower()
            address = match.group(2)

            if chain_name in ('ethereum', 'eth', 'base', 'bsc', 'arbitrum', 'polygon'):
                chain = Chain.EVM
            elif chain_name == 'solana':
                chain = Chain.SOLANA
            else:
                chain = Chain.EVM

            if address.lower() not in self.blacklist and address not in self.blacklist:
                return DetectedContract(
                    address=address,
                    chain=chain,
                    raw_match=match.group(0)
                )

        return None
