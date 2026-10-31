"""Prepare a deterministic extract from an original WSS release; no DB writes.

Rights and publication timestamp must be verified separately before review.
"""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from packages.connectors.india_release import ReleaseManifest
from packages.connectors.rbi_wss import parse_rbi_wss_reserves
from packages.jobs.source_archive import max_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--publication-evidence-url", required=True)
    parser.add_argument("--published-at", required=True, help="independently verified ISO 8601 timestamp with timezone")
    parser.add_argument("--entitlement-basis", required=True, choices=("written-permission", "open-license"))
    parser.add_argument("--definition-version", required=True)
    parser.add_argument("--vintage-id", required=True)
    parser.add_argument("--quality", choices=("verified", "revised"), default="verified")
    parser.add_argument("--extract", type=Path, required=True)
    args = parser.parse_args()
    with args.original.open("rb") as source:
        raw = source.read(max_bytes() + 1)
    if not raw or len(raw) > max_bytes():
        parser.error("Original file exceeds configured archive limit")
    try:
        manifest = ReleaseManifest("rbi", args.source_url, args.publication_evidence_url, datetime.fromisoformat(args.published_at), hashlib.sha256(raw).hexdigest(), args.entitlement_basis, args.definition_version)
        release = parse_rbi_wss_reserves(raw, manifest)
    except ValueError as exc:
        parser.error(str(exc))
    if args.extract.exists():
        parser.error("Extract path already exists; preserve prior reviewed artifacts")
    with args.extract.open("x", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(("indicator_id", "value", "unit", "period_start", "period_end", "vintage_id", "quality"))
        writer.writerow(("fx_gross_reserves_usd", str(release.total_usd_bn), "USD_bn", release.reference_week, release.reference_week, args.vintage_id, args.quality))
    print(json.dumps({"source_sha256": manifest.source_sha256, "extract_sha256": hashlib.sha256(args.extract.read_bytes()).hexdigest(), "reference_week": release.reference_week.isoformat(), "gross_usd_mn": str(release.total_usd_mn), "components_usd_mn": {key: str(getattr(release, key)) for key in ("foreign_currency_assets_usd_mn", "gold_usd_mn", "sdr_usd_mn", "imf_reserve_tranche_usd_mn")}, "published_at": args.published_at, "warning": "SHA-256 matches bytes only; reviewer must independently verify publisher authenticity, exact publication time and entitlement"}, indent=2))


if __name__ == "__main__":
    main()
