"""Read-only fixture rejection diagnostics, isolated from SHA-pinned model sources."""
from datetime import datetime
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")


def fixture_rejection_diagnostic(report):
    """Return a bounded, non-authoritative summary; never promote a fixture."""
    if report.get("reason") != "FIXTURE_NOT_UNIQUELY_VERIFIED":
        return None
    raw = report.get("fixture_diagnostic")
    if not isinstance(raw, dict):
        return {"status": "SOURCE_FIXTURE_EVIDENCE_NOT_EXPOSED",
                "explanation": "Fikstur kaynagi eslesme adaylarini raporlamadi; tahmin uretilmedi."}
    candidates = raw.get("nearby", [])
    if not isinstance(candidates, list):
        candidates = []
    return {"status": "DIAGNOSTIC_ONLY",
            "matched_count": raw.get("matched_count"),
            "nearby": candidates[:5],
            "prediction_allowed": False}


def render_fixture_rejection(report):
    diagnostic = fixture_rejection_diagnostic(report)
    if diagnostic is None:
        return ""
    if diagnostic["status"] == "SOURCE_FIXTURE_EVIDENCE_NOT_EXPOSED":
        return "\nFikstur teshisi: Kaynak aday detaylari mevcut degil; tarih, ev/deplasman ve ESPN mac kimligi incelenmeli."
    return "\nFikstur teshisi: Aday sayisi " + str(diagnostic["matched_count"]) + "; tahmin uretilmedi."
