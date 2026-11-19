"""Manual official club source pilot. DRY_RUN is default; no production writes.

Example:
  PYTHONPATH=. python -m hybrid_engine.official_club_pilot
  PYTHONPATH=. python -m hybrid_engine.official_club_pilot --live --club eurocup_tofas
  PYTHONPATH=. python -m hybrid_engine.official_club_pilot --live --club eurocup_tofas --save
"""
import argparse
import json
from pathlib import Path

from hybrid_engine.official_club_sources import append_receipt,probe,registry


def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true",
                   help="Opt in to bounded robots-respecting requests to the fixed club sites")
    p.add_argument("--club",action="append",default=[],
                   help="Pilot club_key; repeat for several (default: all six)")
    p.add_argument("--save",action="store_true",
                   help="Opt in to append-only metadata receipt in isolated test directory")
    p.add_argument("--article-url",
                   help="Opt in to one freshly indexed official article (requires --live and one --club; no --save)")
    args=p.parse_args(argv)
    if args.save and not args.live:
        p.error("--save requires --live")
    if args.article_url and (not args.live or args.save or len(args.club)!=1):
        p.error("--article-url requires --live and exactly one --club; no --save")
    index=registry()
    selected=[item for item in index if not args.club or item["club_key"] in args.club]
    unknown=sorted(set(args.club)-{r["club_key"] for r in selected})
    if unknown:
        p.error("unknown club_key(s): "+", ".join(unknown))
    if not selected or len(selected)>6:
        p.error("bounded pilot selection required")
    print("ZEYNAL | 2026/27 RESMI KULUP HABER KAYNAGI PILOTU")
    print("MODE:","OPT_IN_NEWS_PAGE_PROBE" if args.live else "DRY_RUN_ZERO_HTTP")
    print("Official pages are NOT lineup truth or confirmed player absence.")
    for item in selected:
        if not args.live:
            print(json.dumps(dict(league=item["league"],club_key=item["club_key"],
                                  site=item["source_url"],status="READY_NOT_FETCHED",
                                  native_team_id=item["native_team_id"],
                                  model_input=False,production_changed=False),
                             ensure_ascii=False,sort_keys=True))
            continue
        if args.article_url:
            from hybrid_engine.official_club_article_probe import probe_article
            result=probe_article(item,args.article_url)
        else:
            result=probe(item)
        if args.save and result.get("status")=="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED":
            path=append_receipt(Path.home()/"zeynal-test-isolated"/"data"/"club-pilot-evidence",result)
            result=dict(result,evidence_file=str(path))
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    print("RESULT: No forecasts, results, score coefficients, or delivery records were modified.")
    return 0


if __name__=="__main__":
    raise SystemExit(run())
