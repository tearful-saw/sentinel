"""
Shared utilities for input validation and sanitization.
"""

import re


EVM_ADDRESS_RE = re.compile(r'^0x[a-fA-F0-9]{40}$')


def is_valid_evm_address(address):
    # type: (str) -> bool
    """Validate that a string is a proper EVM address."""
    return bool(EVM_ADDRESS_RE.match(address))


def sanitize_token_name(name, max_len=50):
    # type: (str, int) -> str
    """Sanitize token name/symbol to prevent LLM prompt injection.
    Strips everything except alphanumeric, spaces, hyphens, dots."""
    clean = re.sub(r'[^a-zA-Z0-9 \-.]', '', name)
    return clean[:max_len].strip() or "UNKNOWN"


def sanitize_symbol(symbol, max_len=20):
    # type: (str, int) -> str
    """Sanitize token symbol."""
    clean = re.sub(r'[^a-zA-Z0-9]', '', symbol)
    return clean[:max_len].strip() or "???"
