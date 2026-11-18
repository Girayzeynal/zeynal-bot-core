"""Read-only forensic trace of FUTURE (not yet tipped) prematch forecast records.

Separate forecast storage, native scheduler journals and Telegram ACK proofs.
Do not mutate first captures, result stores, archive files, model weights or
Telegram polling. Absence of a journal/ACK is NOT proof of manual creation or
non-delivery.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.europe_live import EuropeanRegistry
from hybrid_engine.europe_models import catalog
from hybrid_engine.live_euroleague import names
from ledger_reports import LedgerReports

TSI=ZoneInfo("Europe/Istanbul")


def when(ts):
    return "BILINMIYOR" if not isinstance(ts,int) else datetime.fromtimestamp(ts,TSI).strftime("%Y-%m-%d %H:%M:%S TSİ")


def journals(directory):
    if not directory.is_dir():
        return None
    paths=list(directory.glob("auto-*.json"))
    if len(paths)>4096:raise ValueError("AUTO_JOURNAL_FILE_BUDGET")
    values=[]
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.stat().st_size>128*1024:
            raise ValueError("AUTO_JOURNAL_FILE_INVALID")
        w=json.loads(path.read_text());p=w["payload"]
        if digest(p)!=w["sha256"] or path.stem!="auto-"+w["sha256"]:
            raise ValueError("AUTO_JOURNAL_SHA_CONFLICT")
        values.append(p)
    return values


def telegram_acks(db_path):
    if not db_path.is_file() or db_path.is_symlink():
        return None
    with closing(sqlite3.connect(db_path.as_uri()+"?mode=ro",uri=True,timeout=.2)) as db:
        db.execute("PRAGMA query_only=ON")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_events'").fetchone():
            return None
        rows=db.execute("SELECT payload,sha256 FROM delivery_events LIMIT 100001").fetchall()
    if len(rows)>100000:raise ValueError("DELIVERY_JOURNAL_ROW_BUDGET")
    found=set()
    for raw,pin in rows:
        if len(raw)>256*1024:raise ValueError("DELIVERY_EVENT_SIZE_BUDGET")
        p=json.loads(raw)
        if digest(p)!=pin:raise ValueError("DELIVERY_EVENT_SHA_CONFLICT")
        if (p.get("record_type")=="TELEGRAM_ANALYSIS_DELIVERY"
            and p.get("status")=="TELEGRAM_ACCEPTED"
            and isinstance(p.get("timeline"),dict)):
            sha=p["timeline"].get("snapshot_sha256")
            if isinstance(sha,str) and len(sha)==64:
                found.add(sha)
    return found


def nba_future(root,now):
    db=root/"live-nba"/"nba-hybrid.sqlite"
    if not db.is_file():raise ValueError("NBA_LEDGER_MISSING")
    report=LedgerReports(db).read("NBA")
    if report["status"]!="VERIFIED_LIVE_REPORT":raise ValueError("NBA_NATIVE_REPORT_UNAVAILABLE")
    items=[]
    for r in report["forecasts"]:
        if r["fixture_start_utc"]<=now:continue
        items.append(dict(league="NBA",fixture_id=r["fixture_id"],
            provider_fixture_ids=r["provider_fixture_ids"],home=r["home"],away=r["away"],
            start=r["fixture_start_utc"],created=r["created_utc"],
            generated=r.get("prediction_generated_at_utc"),archived=r.get("first_archived_at_utc"),
            sha=r["snapshot_sha256"],model=r["model_version"],
            fit_cutoff=r.get("parameter_fit_cutoff_utc")))
    return items


def european_future(root,code,now):
    directory=root/"europe"/code.lower()
    if not directory.is_dir():raise ValueError("EUROPE_REGISTRY_MISSING")
    registry=EuropeanRegistry(directory,code)
    items=[]
    for item in registry.independent_records():
        p=item["payload"];g=p["fixture"];start=g["start_ts_utc"]
        if start<=now:continue
        receipt=registry.read_asset(p["fixture_source"])
        b=catalog(receipt,code,g["season_start_year"],max_age=None)
        matches=[v for v in b["payload"]["fixtures"] if v==g]
        if len(matches)!=1:raise ValueError("EUROPE_ARCHIVED_SOURCE_FIXTURE_CONFLICT")
        h,a=names(receipt["document"])[g["provider_fixture_ids"][0]]
        items.append(dict(league=code,fixture_id=g["canonical_id"],
            provider_fixture_ids=g["provider_fixture_ids"],home=h,away=a,
            start=start,created=p["snapshot_created_at_utc"],
            generated=p.get("prediction_generated_at_utc"),
            archived=item["publication"]["first_archived_at_utc"],
            sha=digest(p),model=p.get("version"),fit_cutoff=p.get("feature_cutoff_utc")))
    return items


def auto_evidence(item,auto):
    if auto is None:return "JOURNAL_NOT_PRESENT"
    target_sha=item["sha"]
    matched=[]
    for p in auto:
        if item["league"]=="NBA":
            attempts=p.get("predictions",[])
            current=[e for e in attempts if
                     e.get("snapshot_sha256")==target_sha
                     and e.get("provider_fixture_id") in item["provider_fixture_ids"]
                     and e.get("status")=="ARCHIVED"]
        else:
            section=p.get("leagues",{}).get(item["league"],{})
            attempts=section.get("results",[])
            current=[e for e in attempts if
                     e.get("forecast_sha256")==target_sha
                     and e.get("fixture_id")==item["fixture_id"]
                     and e.get("new_record") is True
                     and e.get("status")=="ANALYSIS_OK"]
        if not current:continue
        first=item["archived"]
        if (type(first) is int and
            type(p.get("evaluated_at_utc")) is int and
            type(p.get("completed_at_utc")) is int and
            p["evaluated_at_utc"]<=first<=p["completed_at_utc"]+60):
            matched.append(p)
    return ("AUTO_SCHEDULER_JOURNAL_SHA_AND_CLOCK_MATCHED" if matched
            else "AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED")


def main():
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--data-directory",default=str(Path.home()/"zeynal-test-isolated"/"data"))
    args=arg.parse_args()
    root=Path(args.data_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():raise ValueError("ISOLATED_EXISTING_DATA_REQUIRED")
    now=int(time.time())
    auto_nba=journals(root/"nba-overnight")
    auto_europe=journals(root/"europe-prematch")
    acks=telegram_acks(root/"telegram-delivery.sqlite")
    records=nba_future(root,now)+european_future(root,"EUROLEAGUE",now)+european_future(root,"EUROCUP",now)
    records.sort(key=lambda r:(r["start"],r["league"],r["fixture_id"]))
    print("ZEYNAL | GELECEK TAHMINLERININ KOKEN DENETIMI | SALT-OKUNUR")
    print("Denetim:",when(now))
    print("Kapsam: Yalniz maçı henüz başlamamış kalıcı orijinal tahminler")
    tally=Counter()
    for i,r in enumerate(records,1):
        origin=auto_evidence(r,auto_nba if r["league"]=="NBA" else auto_europe)
        delivery=("TELEGRAM_SNAPSHOT_ACK_MATCHED" if acks is not None and r["sha"] in acks
                  else "TELEGRAM_ACK_NOT_VERIFIED")
        tally[(r["league"],origin)]+=1
        print(f"\n{i}. {r['league']} | {r['home']} - {r['away']}")
        print("   MAC:",when(r["start"]))
        print("   TAHMIN_URETIM:",when(r["generated"]))
        print("   SNAPSHOT_OLUSTURMA:",when(r["created"]))
        print("   ILK_KALICI_ARSIV:",when(r["archived"]))
        print("   MODEL_FIT_VEYA_FEATURE_CUTOFF:",when(r["fit_cutoff"]))
        print(f"   KANIT: {origin}")
        print(f"   TELEGRAM: {delivery}")
        print(f"   ORIJINAL_SHA: {r['sha'][:20]} | NATIVE_MAC_ID: {','.join(r['provider_fixture_ids'])}")
    print("\nTOPLAM GELECEK_ORIJINAL:",len(records))
    for (league,evidence),count in sorted(tally.items()):
        print(f"{league} | {evidence} | {count}")
    print("Aciklama: AUTO_SCHEDULER... SHA+zaman damgasi ile otomatik kayit kanitidir.")
    print("JOURNAL_NOT_PRESENT/NOT_FOUND manuel kayit kaniti DEGILDIR.")
    print("TELEGRAM_ACK_NOT_VERIFIED mesajin gonderilmedigi kaniti DEGILDIR.")
    print("Hicbir tahmin yeniden uretilmedi, arsiv veya Telegram verisi degistirilmedi.")


if __name__=="__main__":
    main()
