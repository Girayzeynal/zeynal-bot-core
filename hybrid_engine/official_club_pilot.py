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
    p.add_argument("--summary",action="store_true",
                   help="Compact per-club evidence status for safe six-club access audit")
    p.add_argument("--diagnose-links",action="store_true",
                   help="Show bounded same-page link/HTML diagnostic; only with --live, --club and --summary")
    p.add_argument("--save",action="store_true",
                   help="Opt in to append-only NEWS INDEX receipt in isolated test directory")
    p.add_argument("--save-article",action="store_true",
                   help="Opt in to immutable first-observed article VERSION hash receipt in isolated test directory")
    p.add_argument("--article-url",
                   help="Opt in to one freshly indexed official article (requires --live and one --club; no --save)")
    args=p.parse_args(argv)
    if args.save and not args.live:
        p.error("--save requires --live")
    if args.article_url and (not args.live or args.save or len(args.club)!=1):
        p.error("--article-url requires --live and exactly one --club; no --save")
    if args.save_article and (not args.live or not args.article_url or
                             args.save or len(args.club)!=1):
        p.error("--save-article requires --live --article-url and exactly one --club; no --save")
    if args.diagnose_links and (not args.live or len(args.club)!=1 or
                                not args.summary or args.article_url or args.save):
        p.error("--diagnose-links requires --live --summary --club ONE; no --article-url or --save")
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
            result=probe(item,link_diagnostics=True) if args.diagnose_links else probe(item)
        if args.save and result.get("status")=="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED":
            path=append_receipt(Path.home()/"zeynal-test-isolated"/"data"/"club-pilot-evidence",result)
            result=dict(result,evidence_file=str(path))
        if args.save_article and result.get("status")=="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED":
            from hybrid_engine.official_club_capture import record_first_article_capture
            receipt,receipt_file,is_new=record_first_article_capture(result,item)
            result=dict(result,first_capture_receipt_file=str(receipt_file),
                        first_capture_receipt_sha256=receipt["receipt_sha256"],
                        first_capture_at_utc=receipt["captured_at_utc"],
                        first_capture_observed_at_utc=receipt["observed_at_utc"],
                        first_capture_record_new=is_new)
        if args.summary:
            compact=dict(league=result.get("league",item["league"]),
                         club_key=result.get("club_key",item["club_key"]),
                         observation_kind="SINGLE_ARTICLE" if args.article_url else "NEWS_INDEX",
                         status=result.get("status"),
                         source_http_status=result.get("source_http_status"),
                         robots_http_status=result.get("robots_http_status"),
                         publication_time_status=result.get("publication_time_status"),
                         source_url=result.get("source_url",item["source_url"]),
                         model_input=False,production_changed=False)
            if args.article_url:
                # An article receipt contains NO article_links collection. Never
                # misreport that absence as 'zero news discovered'.
                for key in ("index_article_count","index_candidate_origin",
                            "index_raw_date","index_raw_timestamp",
                            "index_clock_status","index_native_post_id",
                            "article_headline_from_index","article_title",
                            "document_bytes","visible_text_chars","body_sha256",
                            "injury_claim_evidence_status","match_identity_status",
                            "first_capture_receipt_file","first_capture_receipt_sha256",
                            "first_capture_at_utc","first_capture_observed_at_utc",
                            "first_capture_record_new"):
                    if key in result:
                        compact[key]=result[key]
                compact["article_claim_candidate_names_text_only"]=[
                    x.get("player_name_text") for x in
                    result.get("injury_absence_claim_candidates",[])]
                compact["article_access_verified"]=(result.get("status")==
                    "OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED" and
                    result.get("source_http_status")==200)
                compact["player_status_verified"]=False
                compact["fixture_verified"]=False
            else:
                # Count exists only when an index successfully supplies links;
                # transport or robots denials are NOT equivalent to zero news.
                if isinstance(result.get("article_links"),list):
                    compact["article_candidate_count"]=len(result["article_links"])
                    compact["embedded_article_candidate_count"]=result.get(
                        "official_embedded_candidate_count",0)
            if args.diagnose_links:
                compact["link_diagnostics"]=result.get("link_diagnostics")
                if item["league"]=="NBA":
                    compact["embedded_diagnostics"]=result.get("embedded_diagnostics")
            print(json.dumps(compact,ensure_ascii=False,sort_keys=True))
        else:
            print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    print("RESULT: No forecasts, results, score coefficients, or delivery records were modified.")
    return 0


if __name__=="__main__":
    raise SystemExit(run())
