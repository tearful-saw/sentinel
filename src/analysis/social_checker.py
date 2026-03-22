"""
Social media verification for tokens.
Checks Twitter account legitimacy and extracts smart money signals
from trading patterns.
"""

import re
import aiohttp
from dataclasses import dataclass
from typing import Optional, List
from loguru import logger


@dataclass
class SocialResult:
    address: str
    # Twitter data
    twitter_handle: str
    twitter_followers: int
    twitter_tweets: int
    twitter_description: str
    twitter_exists: bool
    # Smart money indicators (from trading patterns)
    unique_buyers_1h: int
    unique_sellers_1h: int
    buy_pressure: float        # buys / (buys + sells) in 1h
    volume_acceleration: float # volume_1h * 24 / volume_24h — >1 means accelerating
    # Verdict
    social_score: str         # "strong" | "weak" | "suspicious" | "none"
    flags: List[str]


class SocialChecker:
    """Verifies token social presence and detects smart money patterns."""

    FXTWITTER_URL = "https://api.fxtwitter.com/{}"

    # Suspicious patterns in Twitter bios
    SCAM_KEYWORDS = [
        "guaranteed", "100x", "1000x", "safe", "rugproof",
        "next shib", "next doge", "moonshot", "stealth launch",
    ]

    async def check(self, analysis_result):
        # type: (any) -> Optional[SocialResult]
        """Check social presence and smart money indicators."""
        twitter_handle = ""
        twitter_followers = 0
        twitter_tweets = 0
        twitter_description = ""
        twitter_exists = False
        flags = []

        # 1. Extract Twitter handle from DexScreener data
        if analysis_result.has_twitter:
            # Get handle from DexScreener social URL
            twitter_handle = await self._extract_twitter_handle(analysis_result.address)

        # 2. Check Twitter profile if we have a handle
        if twitter_handle:
            tw = await self._check_twitter(twitter_handle)
            if tw:
                twitter_exists = True
                twitter_followers = tw.get("followers", 0)
                twitter_tweets = tw.get("tweets", 0)
                twitter_description = tw.get("description", "")

                # Analyze Twitter legitimacy
                if twitter_followers < 100:
                    flags.append("Twitter: < 100 followers")
                if twitter_tweets < 10:
                    flags.append("Twitter: < 10 tweets (new/empty account)")

                # Check for scam keywords in bio
                desc_lower = twitter_description.lower()
                for kw in self.SCAM_KEYWORDS:
                    if kw in desc_lower:
                        flags.append("Twitter bio contains '{}'".format(kw))
                        break
            else:
                flags.append("Twitter account not found or deleted")

        # 3. Smart money indicators from trading data
        buys_1h = analysis_result.buys_1h
        sells_1h = analysis_result.sells_1h
        total_1h = buys_1h + sells_1h
        buy_pressure = buys_1h / max(total_1h, 1)

        vol_1h = analysis_result.volume_1h
        vol_24h = analysis_result.volume_24h
        vol_acceleration = (vol_1h * 24) / max(vol_24h, 1) if vol_24h > 0 else 0

        # Smart money signals
        if buy_pressure > 0.7 and buys_1h >= 10:
            flags.append("Strong buy pressure: {:.0%} buys".format(buy_pressure))
        if vol_acceleration > 3.0:
            flags.append("Volume accelerating {:.1f}x vs 24h avg".format(vol_acceleration))
        if buys_1h == 0 and sells_1h == 0:
            flags.append("Zero activity in last hour")

        # 4. Calculate social score
        social_score = "none"
        if twitter_exists:
            if twitter_followers >= 1000 and twitter_tweets >= 50:
                social_score = "strong"
            elif twitter_followers >= 100:
                social_score = "weak"
            else:
                social_score = "suspicious"

            # Override if scam keywords found
            if any("bio contains" in f for f in flags):
                social_score = "suspicious"
        elif analysis_result.has_twitter:
            social_score = "suspicious"  # claimed Twitter but account not found

        result = SocialResult(
            address=analysis_result.address,
            twitter_handle=twitter_handle,
            twitter_followers=twitter_followers,
            twitter_tweets=twitter_tweets,
            twitter_description=twitter_description[:100],
            twitter_exists=twitter_exists,
            unique_buyers_1h=buys_1h,
            unique_sellers_1h=sells_1h,
            buy_pressure=buy_pressure,
            volume_acceleration=vol_acceleration,
            social_score=social_score,
            flags=flags,
        )

        if twitter_exists:
            logger.info("Social: @{} | {} followers | {} tweets | Score: {}".format(
                twitter_handle, twitter_followers, twitter_tweets, social_score,
            ))
        else:
            logger.info("Social: no verified Twitter | Score: {}".format(social_score))

        return result

    async def _extract_twitter_handle(self, token_address):
        # type: (str) -> str
        """Get Twitter handle from DexScreener token data."""
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.dexscreener.com/tokens/v1/base/{}".format(token_address)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if isinstance(data, list) and data:
                        socials = (data[0].get("info") or {}).get("socials") or []
                        for s in socials:
                            if s.get("type") == "twitter":
                                url = s.get("url", "")
                                match = re.search(r'twitter\.com/(\w+)', url)
                                if match:
                                    return match.group(1)
                                match = re.search(r'x\.com/(\w+)', url)
                                if match:
                                    return match.group(1)
        except Exception:
            pass
        return ""

    async def _check_twitter(self, handle):
        # type: (str) -> Optional[dict]
        """Get Twitter profile data via fxtwitter (free, no API key)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.FXTWITTER_URL.format(handle),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    user = data.get("user", {})
                    if not user:
                        return None
                    return {
                        "name": user.get("name", ""),
                        "handle": user.get("screen_name", ""),
                        "followers": user.get("followers", 0),
                        "following": user.get("following", 0),
                        "tweets": user.get("tweets", 0),
                        "description": user.get("description", ""),
                    }
        except Exception:
            return None
