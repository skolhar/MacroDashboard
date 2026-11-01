"""All WSS values and publisher bytes in this file are synthetic fixtures."""
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.india_release import ReleaseManifest
from packages.connectors.rbi_wss import parse_rbi_wss_reserves
from packages.domain.models import Observation, RBIReserveComponent, SourceReleaseReview
from packages.domain.store import observations_at
from packages.jobs.ingest import ingest_records
from packages.jobs.source_archive import archive_original, read_original, max_bytes
from scripts.phase3b_gap_report import coverage


PUBLISHED = datetime(2024, 4, 12, 13, tzinfo=timezone.utc)
SOURCE = "https://www.rbi.org.in/synthetic-test-only"
EVIDENCE = "https://www.rbi.org.in/synthetic-test-notice"


def fixture(total="700000", week="2024-04-05", gold="60000"):
    return f'''<!doctype html><html><body><h1>Weekly Statistical Supplement</h1><p>Week ended: {week}</p><table><tr><th>Item</th><th>Rs. Cr.</th><th>US$ Mn.</th></tr><tr><td>1 Total Reserves</td><td>5800000</td><td>{total}</td></tr><tr><td>1.1 Foreign Currency Assets #</td><td>4900000</td><td>600000</td></tr><tr><td>1.2 Gold</td><td>500000</td><td>{gold}</td></tr><tr><td>1.3 SDRs</td><td>250000</td><td>30000</td></tr><tr><td>1.4 Reserve Position in the IMF</td><td>80000</td><td>10000</td></tr></table></body></html>'''.encode()


def manifest(raw, published=PUBLISHED):
    return ReleaseManifest("rbi", SOURCE, EVIDENCE, published, hashlib.sha256(raw).hexdigest(), "written-permission", "rbi-wss-gross-reserves-v1")


def extract(value="700", vintage="original"):
    return f"indicator_id,value,unit,period_start,period_end,vintage_id,quality\nfx_gross_reserves_usd,{value},USD_bn,2024-04-05,2024-04-05,{vintage},verified\n".encode()


def synthetic_pdf():
    lines = ["Weekly Statistical Supplement", "Week ended: 2024-04-05", "Item Rs. Cr. US$ Mn.", "1 Total Reserves 5800000 700000", "1.1 Foreign Currency Assets 4900000 600000", "1.2 Gold 500000 60000", "1.3 SDRs 250000 30000", "1.4 Reserve Position in the IMF 80000 10000"]
    content = "BT /F1 11 Tf 40 750 Td 15 TL " + " Tj T* ".join("(" + line.replace("(", "\\(").replace(")", "\\)") + ")" for line in lines) + " Tj ET"
    data = content.encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 700 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Root 1 0 R /Size {len(offsets)} >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def test_wss_html_units_components_dates_and_strict_rejection():
    raw = fixture()
    release = parse_rbi_wss_reserves(raw, manifest(raw))
    assert release.reference_week == date(2024, 4, 5)
    assert release.published_at == PUBLISHED
    assert release.total_usd_mn == Decimal("700000")
    assert release.total_usd_bn == Decimal("700")
    assert release.foreign_currency_assets_usd_mn == Decimal("600000")
    assert release.gold_usd_mn == Decimal("60000")
    with pytest.raises(ValueError, match="component sum"):
        parse_rbi_wss_reserves(fixture(total="700004"), manifest(fixture(total="700004")))
    with pytest.raises(ValueError, match="reference week"):
        ambiguous = raw.replace(b"</body>", b"<p>As on 2024-04-12</p></body>")
        parse_rbi_wss_reserves(ambiguous, manifest(ambiguous))
    with pytest.raises(ValueError, match="definition"):
        parse_rbi_wss_reserves(raw, replace(manifest(raw), definition_version="rbi-other-v1"))
    with pytest.raises(ValueError, match="Unsupported"):
        parse_rbi_wss_reserves(b"synthetic not a publisher format", manifest(raw))


def test_wss_text_layer_pdf_uses_same_strict_definition():
    raw = synthetic_pdf()
    assert parse_rbi_wss_reserves(raw, manifest(raw)).total_usd_bn == Decimal("700")


def test_archive_large_concurrent_integrity_and_corruption(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("SOURCE_ARCHIVE_MAX_BYTES", "1000000")
    raw = b"synthetic original " * 50000
    assert len(raw) > 750000
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(archive_original, [raw] * 8))
    assert sum(item["created"] for item in results) == 1
    assert all(item["sha256"] == results[0]["sha256"] for item in results)
    assert read_original(results[0]["reference"], results[0]["sha256"]) == raw
    with pytest.raises(ValueError, match="limit"):
        archive_original(b"x" * (max_bytes() + 1))
    stored = tmp_path / "archive" / "sha256" / results[0]["sha256"]
    stored.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        read_original(results[0]["reference"], results[0]["sha256"])
    with pytest.raises(ValueError, match="differ"):
        archive_original(raw)


def test_governed_import_duplicate_revision_and_point_in_time(db, tmp_path, monkeypatch):
    import apps.api.main as api
    monkeypatch.setenv("SOURCE_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    for index, raw in enumerate((fixture(), fixture(total="700001", gold="60001"))):
        approved = archive_original(raw)
        normalized = extract("700" if index == 0 else "700.001", "original" if index == 0 else "revised")
        published = PUBLISHED if index == 0 else datetime(2024, 4, 19, 13, tzinfo=timezone.utc)
        review = SourceReleaseReview(provider="rbi", source_reference=SOURCE, original_archive_reference=approved["reference"], source_sha256=approved["sha256"], extract_sha256=hashlib.sha256(normalized).hexdigest(), published_at=published, publication_evidence_url=EVIDENCE, publication_evidence_note="Synthetic independent publication evidence for regression test", entitlement_basis="written-permission", entitlement_reference="https://www.rbi.org.in/synthetic-permission", definition_version="rbi-wss-gross-reserves-v1", submitted_by="operator-a", submitted_at=PUBLISHED, status="approved", approved_by="operator-b", approved_at=PUBLISHED, review_note="Synthetic reviewer approval for regression test")
        db.add(review)
        db.commit()
        payload = api.ReleasePackageRequest(review_id=review.id, provider="rbi", source_reference=SOURCE, publication_evidence_url=EVIDENCE, published_at=published, source_sha256=approved["sha256"], redistribution_basis="written-permission", definition_version="rbi-wss-gross-reserves-v1", original_source_base64=base64.b64encode(raw).decode(), extract_csv_base64=base64.b64encode(normalized).decode())
        outcome = api.import_release(payload, {"operator_id": "operator-a"})
        assert outcome["inserted"] == 1
        assert api.import_release(payload, {"operator_id": "operator-a"})["duplicate"] == 1
    rows = db.scalars(select(Observation).where(Observation.indicator_id == "fx_gross_reserves_usd", Observation.is_demo.is_(False)).order_by(Observation.published_at)).all()
    assert len(rows) == 2 and rows[-1].is_revision
    assert db.get(RBIReserveComponent, rows[-1].id).total_usd_mn == Decimal("700001")
    before = datetime(2024, 4, 12, 12, tzinfo=timezone.utc)
    published = datetime(2024, 4, 13, tzinfo=timezone.utc)
    assert observations_at(db, "fx_gross_reserves_usd", before, "source_known", False) == []
    assert observations_at(db, "fx_gross_reserves_usd", published, "source_known", False)[0].value == Decimal("700")
    assert observations_at(db, "fx_gross_reserves_usd", published, "system_known", False) == []
    assert observations_at(db, "fx_gross_reserves_usd", datetime.now(timezone.utc), "system_known", False)[0].value == Decimal("700.001")
    view = api.external_liquidity()
    assert view["rbi_reserves"]["gross_usd_mn"] == 700001
    assert view["rbi_reserves"]["reviewed_by"] == "operator-b"
    assert view["cycle"]["score"] is None
    assert view["signals"]["gross_reserve_decline"] is None
    gaps = coverage(db, datetime(2024, 4, 13, tzinfo=timezone.utc))["indicators"]["fx_gross_reserves_usd"]
    assert "2024-04-05" in gaps["missing_expected_friday_weeks_system_known"]


def test_reviewed_extract_cannot_override_original_total(db, tmp_path, monkeypatch):
    import apps.api.main as api
    from fastapi import HTTPException
    monkeypatch.setenv("SOURCE_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    raw = fixture()
    archived = archive_original(raw)
    wrong = extract("701")
    review = SourceReleaseReview(provider="rbi", source_reference=SOURCE, original_archive_reference=archived["reference"], source_sha256=archived["sha256"], extract_sha256=hashlib.sha256(wrong).hexdigest(), published_at=PUBLISHED, publication_evidence_url=EVIDENCE, publication_evidence_note="Synthetic independent publication evidence for regression test", entitlement_basis="written-permission", entitlement_reference="https://www.rbi.org.in/synthetic-permission", definition_version="rbi-wss-gross-reserves-v1", submitted_by="operator-a", submitted_at=PUBLISHED, status="approved", approved_by="operator-b", approved_at=PUBLISHED, review_note="Synthetic reviewer approval for regression test")
    db.add(review)
    db.commit()
    payload = api.ReleasePackageRequest(review_id=review.id, provider="rbi", source_reference=SOURCE, publication_evidence_url=EVIDENCE, published_at=PUBLISHED, source_sha256=archived["sha256"], redistribution_basis="written-permission", definition_version="rbi-wss-gross-reserves-v1", original_source_base64=base64.b64encode(raw).decode(), extract_csv_base64=base64.b64encode(wrong).decode())
    with pytest.raises(HTTPException, match="does not match original WSS"):
        api.import_release(payload, {"operator_id": "operator-a"})
    assert not db.scalars(select(Observation).where(Observation.indicator_id == "fx_gross_reserves_usd", Observation.is_demo.is_(False))).all()
