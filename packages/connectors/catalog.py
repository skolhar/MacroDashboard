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
    SourcePlan("rbi", ("usd_inr_spot", "india_10y_yield", "fx_gross_reserves_usd", "rbi_net_forward_usd"), "reviewed_release_only", "https://statistics.rbi.org.in/", "DBIE downloads exist; automated reuse and redistribution rights unconfirmed. Forward-position sign and maturity mapping blocked"),
    SourcePlan("nsdl", ("fpi_equity_net_inr", "fpi_debt_net_inr"), "reviewed_release_only", "https://pilot.fpi.nsdl.co.in/Reports/Latest.aspx", "Provisional versus confirmed trade basis and redistribution rights require review"),
    SourcePlan("amfi", ("sip_contribution_inr", "smallcap_mf_net_inr", "midcap_mf_net_inr"), "reviewed_release_only", "https://www.amfiindia.com/terms-of-use", "AMFI terms limit reuse to personal non-commercial use absent written agreement"),
    SourcePlan("mospi", ("india_cpi_yoy",), "manual_only", "https://mospi.gov.in/", "Release timing and revision policy require operator review"),
    SourcePlan("licensed_market", ("brent_usd", "dxy", "nasdaq100_price", "us_high_yield_oas", "nifty_eps_revision_3m", "midcap150_pe", "smallcap250_pe"), "unavailable", "https://www.nseindia.com/", "No licensed redistribution entitlement or API credentials supplied"),
    SourcePlan("licensed_brent", ("brent_usd",), "reviewed_release_only", "https://www.ice.com/products/219/Brent-Crude-Futures", "Requires a licensed provider with redistribution and historical rights"),
)


def adapter_for(provider: str):
    plan = next((item for item in SOURCE_PLANS if item.provider == provider), None)
    if plan is None:
        raise ValueError("Unknown source provider")
    return TreasuryAdapter() if plan.access == "official_xml" else UnavailableAdapter(plan.provider, plan.indicators, plan.reason)
