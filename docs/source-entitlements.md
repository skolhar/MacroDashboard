# Source access and redistribution register

The adapter catalog is an access-control inventory, not a claim that every public webpage permits automated collection or redistribution. No restricted site was scraped and no commercial key was assumed.

| Source / indicators | Integration | Staging observation status | Public redistribution position |
|---|---|---|---|
| [U.S. Treasury daily par yield XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed), 10Y | Official unauthenticated XML, bounded response, retries, source URL and vintage | **Connected:** 21 official rows from October 2026 ingested in isolated local staging on 31 October 2026; second request inserted 0 duplicates | Official U.S. government publication. Confirm any downstream display terms and attribution before public launch. Original historical release timestamps are absent from XML; first ingestion time is used conservatively. |
| [RBI DBIE](https://data.rbi.org.in/): USD/INR, India 10Y, reserves, forward position | Reviewed manual import only | No verified observations | Machine-readable endpoint, terms, publication timing and RBI forward sign/maturity semantics pending. |
| [NSDL FPI](https://www.fpi.nsdl.co.in/): equity/debt flows | Reviewed manual import only | No verified observations | Field definitions, release timing and reuse terms pending. |
| [AMFI](https://www.amfiindia.com/mutual-fund): SIP and category flows | Reviewed manual import only | No verified observations | Monthly data definitions and public display rights pending. |
| [MoSPI](https://mospi.gov.in/): CPI | Reviewed manual import only | No verified observations | Release and revision policy pending. |
| Brent, DXY, Nasdaq 100, U.S. HY spreads, Nifty earnings/valuation | Explicit `DATA_UNAVAILABLE` adapter | No verified observations | Licensed provider credentials and redistribution rights required. |
| Indian IT filings, software exports and DII flows | Manual research path only | No verified observations | Comparable methodology and exact publication/vintage records required. |

Manual imports require a named, scoped operator, a source URL and a public-redistribution attestation. This is an operator assertion, not automated license verification. If rights are uncertain, do not import; leave `DATA_UNAVAILABLE`. The bundled Phase 1 synthetic fixture remains isolated in demo mode and is never counted as source-backed.
