"""Explicit provider access registry. No unlicensed fallback or scraping."""
from dataclasses import dataclass
from .base import UnavailableAdapter
from .treasury import TreasuryAdapter


@dataclass(frozen=True)
class SourcePlan:
    provider: str
    indicators: tuple[str, ...]
    access: str
    reference: str
    reason: str


SOURCE_PLANS = (
    SourcePlan("us_treasury", ("us_10y_yield",), "official_xml", "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed", "Official public feed; actual publication time absent from historical XML"),
    SourcePlan("rbi", ("usd_inr_spot", "india_10y_yield", "fx_gross_reserves_usd", "rbi_net_forward_usd"), "manual_only", "https://data.rbi.org.in/", "No approved machine-readable endpoint and redistribution review on file"),
    SourcePlan("nsdl", ("fpi_equity_net_inr", "fpi_debt_net_inr"), "manual_only", "https://www.fpi.nsdl.co.in/", "Official release fields and reuse terms require operator review"),
    SourcePlan("amfi", ("sip_contribution_inr", "smallcap_mf_net_inr", "midcap_mf_net_inr"), "manual_only", "https://www.amfiindia.com/mutual-fund", "Monthly publication and category definitions require operator review"),
    SourcePlan("mospi", ("india_cpi_yoy",), "manual_only", "https://mospi.gov.in/", "Release timing and revision policy require operator review"),
    SourcePlan("licensed_market", ("brent_usd", "dxy", "nasdaq100_price", "us_high_yield_oas", "nifty_eps_revision_3m", "midcap150_pe", "smallcap250_pe"), "unavailable", "https://www.nseindia.com/", "No licensed redistribution entitlement or API credentials supplied"),
)


def adapter_for(provider: str):
    plan = next((item for item in SOURCE_PLANS if item.provider == provider), None)
    if plan is None:
        raise ValueError("Unknown source provider")
    return TreasuryAdapter() if plan.access == "official_xml" else UnavailableAdapter(plan.provider, plan.indicators, plan.reason)
