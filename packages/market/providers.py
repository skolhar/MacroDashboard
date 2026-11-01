"""Single provider switch; future adapters implement MarketProvider."""
from .base import MarketProvider
from .yahoo import YahooProvider, MarketSourceUnavailable


def provider_for(name: str) -> MarketProvider:
    if name == "yahoo":
        return YahooProvider()
    if name == "upstox":
        raise MarketSourceUnavailable("UpstoxAdapterUnavailable")
    raise ValueError("Unknown market-data provider")
