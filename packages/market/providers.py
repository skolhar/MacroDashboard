"""Provider switch; adapters implement MarketProvider."""
from .base import MarketProvider
from .yahoo import YahooProvider, MarketSourceUnavailable
from .tapetide import TapetideProvider


def provider_for(name: str) -> MarketProvider:
    if name == "yahoo":
        return YahooProvider()
    if name == "tapetide":
        return TapetideProvider()
    if name == "upstox":
        raise MarketSourceUnavailable("UpstoxAdapterUnavailable")
    raise ValueError("Unknown market-data provider")
