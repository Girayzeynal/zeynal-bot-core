"""TEST ONLY: one MoviOdds live basketball board, compare against saved 44-game NBA week.

No Telegram token, production write, scheduler, or fabricated odds. Never
prints API keys or individual unverified prices. Suitable for past/future
fixtures: a past game absent from today's board is NOT 'no odds existed'.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

from hybrid_engine.movi_bulk_pilot import read_live_board, league_id, utc_time, classify_http_error
from hybrid_engine.movi_nba_espn_week import code_of


def compare_week(snapshot: dict, board: dict) -> dict:
    games = snapshot.get("games")
    if (snapshot.get("status") != "OK" or
            snapshot.get("kind") != "SAVED_SNAPSHOT_NOT_LIVE_DATA" or
            not isinstance(games, list) or not isinstance(board.get("matches"), list)):
        return {"status": "BAD_SCHEMA"}
    nba = {}
    for m in board["matches"]:
        if not isinstance(m, dict) or league_id(m.get("league")) != "NBA":
            continue
        a, h = code_of(m.get("away")), code_of(m.get("home"))
        if not a or not h or a == h:
            continue
        k = utc_time(m.get("kickoff_utc"))
        if k is None:
            continue
        # Same teams within 24 hours, independent of provider's +10m kickoff.
        nba.setdefault((a, h), []).append((k, m))
    now = datetime.now(timezone.utc)
    rows = []
    counts = Counter()
    for g in games:
        at = utc_time(g.get("utc"))
        a, h = g.get("away_code"), g.get("home_code")
        if at is None or not a or not h:
            return {"status": "BAD_SNAPSHOT_FIXTURE"}
        candidates = [(abs((k-at).total_seconds()), m) for k,m in nba.get((a,h), [])
                      if abs((k-at).total_seconds()) <= 24*3600]
        candidates.sort(key=lambda x:x[0])
        m = candidates[0][1] if candidates else None
        # Snapshot date is authoritative for date; no provider kickoff rewrite.
        if m is None:
            state = "NOT_IN_CURRENT_PROVIDER_BOARD"
            quote_count = 0
        else:
            quotes = m.get("quotes") if isinstance(m.get("quotes"), list) else []
            quote_count = sum(
                isinstance(q,dict) and q.get("suspended") is not True
                and isinstance(q.get("odds_dec"),(int,float))
                and not isinstance(q.get("odds_dec"),bool)
                and 1 < q["odds_dec"] < 1000
                for q in quotes
            )
            state = "BOARD_WITH_PRICES_UNVERIFIED_FRESHNESS" if quote_count else "BOARD_NO_ACTIVE_PRICES"
        counts[state] += 1
        rows.append({"date_tsi":g["date_tsi"],"start_tsi":g["start_tsi"],
                     "away":g["away"],"home":g["home"],"state":state,
                     "active_price_rows":quote_count,
                     "already_started":at <= now})
    return {"status":"OK","source":"MOVIODDS_ONE_LIVE_ODDS_BOARD",
            "network_calls_moviodds":1,"snapshot_week":snapshot.get("period_tsi"),
            "total":len(rows),"counts":dict(counts),"matches":rows,
            "warning":"Current provider board is NOT a full 7-day odds history. Price freshness not verified."}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--live",action="store_true")
    ap.add_argument("--cached",default="nba_week_21_27_snapshot.json")
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()
    if not args.live or os.getenv("ZEYNAL_MOVIODDS_ENABLED")!="1" or not os.getenv("ZEYNAL_MOVIODDS_KEY"):
        print("NOT_AUTHORIZED: --live and ZEYNAL_MOVIODDS_ENABLED=1 and ZEYNAL_MOVIODDS_KEY required")
        return
    try:
        saved=json.loads(Path(args.cached).read_text(encoding="utf-8"))
        result=compare_week(saved,read_live_board(os.environ["ZEYNAL_MOVIODDS_KEY"]))
    except HTTPError as e:
        result={"status":"HTTP_ERROR","code":e.code,"reason":classify_http_error(e)}
        e.close()
    except (OSError,URLError,ValueError,TypeError):
        result={"status":"SOURCE_UNAVAILABLE"}
    if args.json or result.get("status")!="OK":
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    print("ZEYNAL TEST | NBA HAFTALIK PIYASA KONTROLU")
    print("DURUM:",result["status"],"| MOVIODDS ISTEK:",result["network_calls_moviodds"])
    print("MAC:",result["total"],"|",json.dumps(result["counts"],ensure_ascii=False))
    for r in result["matches"]:
        print(r["start_tsi"],r["away"],"@",r["home"],
              "|",r["state"],"| FIYAT SATIRI:",r["active_price_rows"])
    print("NOT: Bu mevcut bulten taramasidir; gecmis veya gelecek 7 gunun tum oranlari garanti degildir.")
    print("NOT: Fiyat guncelligi ve Telegram'a mesaj teslimi bu komutta test edilmez.")


if __name__=="__main__":
    main()
