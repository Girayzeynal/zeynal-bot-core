"""One-shot, archive-safe final reconciliation and unified NBA/EuroLeague/EuroCup report.

Run only against the user's isolated test archives, not Fly production. A FINAL
is accepted only by existing native/source-pinned settlement implementations.
Old forecasts and their first-publication clocks are never changed.
"""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

from hybrid_engine.archive_audit import audit_ledger
from hybrid_engine.europe_live import EuropeanRegistry, EuropeanService
from hybrid_engine.europe_models import season_url
from hybrid_engine.europe_reports import EuropeanReports
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.nba_ledger_settlement import settle as settle_nba
from hybrid_engine.prospective_results import OFFICIAL, ProspectiveResults
from ledger_reports import LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_collect import fetch_document

ZONE = ZoneInfo("Europe/Istanbul")


def classification(row, now):
    if row.get("actual") is not None:
        return "FINAL_MATCHED"
    if row["fixture_start_utc"] > now:
        return "NOT_STARTED"
    return "STARTED_FINAL_NOT_VERIFIED"


def report_league(code, report, now):
    """One fixture once; keep separately published model components visible."""
    fixtures = {}
    for row in report.get("forecasts", []):
        key = (row["league"], row["season"], row["fixture_id"])
        fixtures.setdefault(key, []).append(row)
    ordered = sorted(fixtures.values(), key=lambda rows: (rows[0]["fixture_start_utc"], rows[0]["fixture_id"]))
    matched = sum(any(r.get("actual") is not None for r in group) for group in ordered)
    started_unmatched = sum(group[0]["fixture_start_utc"] <= now and
                            not any(r.get("actual") is not None for r in group) for group in ordered)
    not_started = len(ordered) - matched - started_unmatched
    print(f"\n### {code} | ARSIV={len(ordered)} | FINAL_ESLESTI={matched} | "
          f"BASLAMIS_FINAL_DOGRULANMADI={started_unmatched} | BASLAMADI={not_started}")
    for group in ordered:
        first = group[0]
        status = "FINAL_MATCHED" if any(r.get("actual") is not None for r in group) else classification(first, now)
        tip = datetime.fromtimestamp(first["fixture_start_utc"], ZONE).strftime("%Y-%m-%d %H:%M")
        print(f"{tip} TSİ | {first['home']} - {first['away']} | {status} | id={first['fixture_id'][:20]}")
        if status != "FINAL_MATCHED":
            continue
        for row in group:
            if row.get("actual") is None:
                continue
            actual = row["actual"]
            predicted = row["prediction"]
            error = sum(predicted) - sum(actual)
            print(f"   model={row['model_version'][:60]} | tahmin={predicted[0]:.2f}-{predicted[1]:.2f} "
                  f"| normal_sure={actual[0]}-{actual[1]} "
                  f"| toplam_hata={error:+.2f}")
            quarters = row.get("predicted_quarters")
            actual_periods = row.get("actual_periods")
            if quarters is not None and actual_periods is not None:
                qs = [sum(quarters[q]) - actual_periods["home"][q] -
                      actual_periods["away"][q] for q in range(4)]
                print("   1Q..4Q toplam hatalari: " +
                      " | ".join(f"{q:+.2f}" for q in qs) +
                      f" | 1H={sum(qs[:2]):+.2f} | 2H={sum(qs[2:]):+.2f}")
            if row.get("legacy_publication_clock_unrecorded"):
                print("   UYARI: eski kaydin ilk yayin zamani kanitli degil; canli basari metrigine katilamaz")
    for cohort in report.get("groups", []):
        print(f"PERFORMANS | {code} | model={cohort['model_version'][:50]} "
              f"| n={cohort['n']} | takim_MAE={cohort['team_mae']:.2f} "
              f"| toplam_MAE={cohort['total_mae']:.2f}")
    return dict(league=code, fixtures=len(ordered), matched=matched,
                started_unmatched=started_unmatched, not_started=not_started)


def nba(root, apply, now):
    db = root / "live-nba" / "nba-hybrid.sqlite"
    if not db.is_file() or db.is_symlink():
        raise ValueError("NBA_EXISTING_LEDGER_REQUIRED")
    audit = audit_ledger(db, assets_directory=root / "live-nba" / "assets")
    if (audit["sqlite_integrity"] != "ok" or audit["issues"] or
            any(row["findings"] for row in audit["rows"])):
        raise ValueError("NBA_ARCHIVE_INTEGRITY_BLOCKS_SETTLEMENT")
    before = LedgerReports(db).read("NBA")
    if before["status"] != "VERIFIED_LIVE_REPORT":
        raise ValueError("NBA_VERIFIED_LEDGER_REQUIRED")
    due = [r for r in before["forecasts"]
           if r.get("actual") is None and r["fixture_start_utc"] < now]
    print(f"NBA | ondenetim: {len(before['forecasts'])} tahmin, "
          f"{len(due)} baslamis/eslesmemis")
    if apply and due:
        # Constructor is used only after the existing schema and native pins pass.
        # The existing implementation appends FINAL rows; PREMATCH rows are immutable.
        ledger = LiveAnalysisLedger(db)
        print("NBA | native settlement:", settle_nba(ledger))
    elif not apply:
        print("NBA | REPORT_ONLY: saglayici sorgusu ve sonuc yazimi yapilmadi")
    after = LedgerReports(db).read("NBA")
    if after["status"] != "VERIFIED_LIVE_REPORT":
        raise ValueError("NBA_POST_SETTLEMENT_REPORT_INVALID")
    return report_league("NBA", after, now)


def legacy_euroleague(root, apply, now, receipts):
    legacy_dir = Path.home() / "zeynal-test-isolated" / "archive"
    if not legacy_dir.is_dir():
        return None, "LEGACY_ARCHIVE_NOT_PRESENT"
    archive = FrozenArchive(legacy_dir)
    results = ProspectiveResults(archive, root / "official-results")
    previous = results.outcomes()
    due = [p for fid, p in archive.records.items()
           if fid not in previous and p["fixture"]["start_ts_utc"] < now]
    if apply and due:
        receipt = receipts.get(OFFICIAL)
        if receipt is None:
            receipt = fetch_document("EUROLEAGUE_LIVE", OFFICIAL)
            receipts[OFFICIAL] = receipt
        if receipt.get("status") == "DOCUMENT_RECEIVED":
            added = results.ingest(receipt)
            print(f"EUROLEAGUE_LEGACY | yeni={len(added['inserted'])} "
                  f"| halen_bekleyen={len(added['pending'])}")
        else:
            print(f"EUROLEAGUE_LEGACY | KAYNAK_ENGELI={receipt.get('status')}")
    return results, f"records={len(archive.records)}, due={len(due)}, settled={len(results.outcomes())}"


def european(root, code, apply, now, receipts, legacy_results=None):
    directory = root / "europe" / code.lower()
    if not directory.is_dir():
        print(f"{code} | NO_CURRENT_REGISTRY")
        return None
    registry = EuropeanRegistry(directory, code)
    rows = registry.records()
    due = [item for item in rows
           if item["payload"]["fixture"]["start_ts_utc"] < now
           and registry.outcome(item["payload"]) is None]
    years = sorted({item["payload"]["fixture"]["season_start_year"] for item in due})
    if len(years) > 5:
        raise ValueError("EUROPE_SETTLEMENT_SEASON_BUDGET")
    print(f"{code} | ondenetim: {len(rows)} orijinal kayit, "
          f"{len(due)} baslamis/eslesmemis, sezon={years}")
    if apply:
        for year in years:
            url = season_url(code, year)
            receipt = receipts.get(url)
            if receipt is None:
                receipt = fetch_document("EUROLEAGUE_LIVE", url)
                receipts[url] = receipt
            if receipt.get("status") != "DOCUMENT_RECEIVED":
                print(f"{code} | sezon={year} | KAYNAK_ENGELI={receipt.get('status')} "
                      f"| HTTP={receipt.get('http_status')}")
                continue
            # A conflicting earlier fixture must not hide an unrelated valid FINAL.
            # Keep the native EuropeanRegistry.settle() validators unchanged,
            # but scope each append attempt to exactly one original forecast.
            class PerFixtureRegistry(EuropeanRegistry):
                def __init__(self, directory, league, record):
                    super().__init__(directory, league)
                    self.record = record

                def records(self):
                    return [self.record]

            added_count = 0
            failed = 0
            for item in [item for item in due
                         if item["payload"]["fixture"]["season_start_year"] == year]:
                try:
                    one = PerFixtureRegistry(directory, code, item)
                    added_count += len(one.settle(receipt, year))
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    failed += 1
                    print(f"{code} | mac={item['payload']['fixture']['canonical_id'][:20]} "
                          f"| FINAL_BLOKE={type(exc).__name__}")
            print(f"{code} | sezon={year} | YENI_DOGRULANMIS_FINAL={added_count} "
                  f"| MAC_BAZINDA_ENGEL={failed}")
    else:
        print(f"{code} | REPORT_ONLY: saglayici sorgusu ve sonuc yazimi yapilmadi")
    service = EuropeanService(code, directory, root / "europe" / "models", fetch_document)
    result = EuropeanReports(service, legacy_results if code == "EUROLEAGUE" else None).read(code)
    return report_league(code, result, now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory",
                        default=str(Path.home() / "zeynal-test-isolated" / "data"))
    parser.add_argument("--apply", action="store_true",
                        help="Use existing native source parsers to append FINAL outcomes only")
    args = parser.parse_args()
    root = Path(args.data_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("EXISTING_ISOLATED_DATA_DIRECTORY_REQUIRED")
    if root == Path("/data") or "/data" == str(root):
        raise ValueError("PRODUCTION_DATA_DIRECTORY_FORBIDDEN")
    now = int(time.time())
    print("ZEYNAL | TUM LIGLER | NORMAL SURE | TURKIYE SAATI")
    print("MOD:", "FINAL_SYNC_APPEND_ONLY" if args.apply else "REPORT_ONLY")
    print("Denetim tarihi:", datetime.fromtimestamp(now, ZONE).isoformat())
    print("Yalniz kaynakta FINAL olan maclar eslestirilir; PREMATCH kayitlarina dokunulmaz.")
    errors = []
    receipts = {}
    stats = []
    for code, fn in (
        ("NBA", lambda: nba(root, args.apply, now)),
        ("EUROLEAGUE_LEGACY", lambda: legacy_euroleague(root, args.apply, now, receipts)),
        ("EUROLEAGUE", lambda: european(root, "EUROLEAGUE", args.apply, now,
                                       receipts, legacy_results=legacy)),
        ("EUROCUP", lambda: european(root, "EUROCUP", args.apply, now, receipts)),
    ):
        try:
            if code == "EUROLEAGUE_LEGACY":
                legacy, detail = fn()
                print("EUROLEAGUE_LEGACY |", detail)
            else:
                result = fn()
                if result is not None:
                    stats.append(result)
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, RuntimeError) as exc:
            if code == "EUROLEAGUE_LEGACY":
                legacy = None
            errors.append((code, type(exc).__name__))
            print(f"{code} | ENGEL: {type(exc).__name__}")
    print("\nTOPLU DURUM |", " | ".join(
        f"{r['league']}: {r['matched']}/{r['fixtures']} final, "
        f"{r['started_unmatched']} baslamis/eslesmemis, {r['not_started']} baslamamis"
        for r in stats))
    print("Not: Baslamis ama eslesmemis = devam ediyor veya saglayici FINAL kaniti eksik.")
    print("Not: Orijinal tahmini bulunmayan eski mac icin tahmin uydurulmaz.")
    print("Not: O/U market sonucu icin tahmin anina ait dogrulanmis barem ve kural gerekir.")
    if errors:
        print("TAMAMLANMAYAN HATLAR:", errors)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
