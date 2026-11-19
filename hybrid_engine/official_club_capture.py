"""Opt-in immutable *first captured article VERSION* metadata receipt.

Per (club URL, sha256 of HTTP article bytes) an exclusive immutable file
records the earliest capture performed through this isolated test tool.
No article HTML/body or player names are stored. Re-observation never
changes the first version's timestamp. The filesystem receipt provides
auditability, not an external trusted timestamp authority.
"""
from pathlib import Path
import hashlib
import json
import re
import time

from hybrid_engine.official_club_sources import _bounded_https

RECEIPT_FORMAT="OFFICIAL_CLUB_CAPTURE_RECEIPT_V1"
_ALLOWED_ROOT=(Path.home()/"zeynal-test-isolated"/"data"/"club-pilot-evidence").absolute()
_SHA=re.compile(r"^[0-9a-f]{64}$")


def _packed(payload):
    return json.dumps(payload,ensure_ascii=False,allow_nan=False,
                      sort_keys=True,separators=(",",":")).encode("utf-8")


def _verify_folder(root):
    root=Path(root).expanduser().absolute()
    if root!=_ALLOWED_ROOT:
        raise ValueError("ISOLATED_CLUB_CAPTURE_DIRECTORY_REQUIRED")
    if any(node.is_symlink() for node in
           (root,root.parent,root.parent.parent,root.parent.parent.parent)):
        raise ValueError("ISOLATED_CAPTURE_SYMLINK_REFUSED")
    root.mkdir(parents=True,exist_ok=True)
    return root


def verify_article_capture(receipt):
    """Reject any altered, unpinned or timestamp-inconsistent receipt."""
    if type(receipt) is not dict:
        raise ValueError("CAPTURE_RECEIPT_REQUIRED")
    digest=receipt.get("receipt_sha256")
    if not isinstance(digest,str) or not _SHA.fullmatch(digest):
        raise ValueError("CAPTURE_RECEIPT_SHA_REQUIRED")
    original={k:v for k,v in receipt.items() if k!="receipt_sha256"}
    if hashlib.sha256(_packed(original)).hexdigest()!=digest:
        raise ValueError("CAPTURE_RECEIPT_IMMUTABLE_PIN_CONFLICT")
    if receipt.get("format")!=RECEIPT_FORMAT:
        raise ValueError("CAPTURE_RECEIPT_FORMAT_CONFLICT")
    url=receipt.get("source_url")
    _bounded_https(url)
    sha=receipt.get("body_sha256")
    if not isinstance(sha,str) or not _SHA.fullmatch(sha):
        raise ValueError("CAPTURE_RECEIPT_ARTICLE_BODY_PIN")
    observed=receipt.get("observed_at_utc")
    captured=receipt.get("captured_at_utc")
    if (type(observed) is not int or type(captured) is not int or
        not 0<observed<=captured<=observed+600):
        raise ValueError("CAPTURE_RECEIPT_CLOCK_INVALID")
    club_key=receipt.get("club_key")
    if not isinstance(club_key,str) or not re.fullmatch(r"[a-z0-9_]{4,80}",club_key):
        raise ValueError("CAPTURE_RECEIPT_CLUB_KEY_INVALID")
    return receipt


def record_first_article_capture(article,club,*,root=None,now_utc=None):
    """Store metadata only after a live 200 page observation.

    Subsequent calls for an identical article URL+raw body bytes hash return
    the first saved receipt unchanged, never move first-captured time back
    or overwrite a previous version. If the article changed, a new version
    gets a new receipt and its own current first-observed timestamp.
    """
    if type(article) is not dict or type(club) is not dict:
        raise ValueError("LIVE_ARTICLE_AND_CLUB_REQUIRED")
    url=article.get("source_url")
    p=_bounded_https(url)
    canonical=_bounded_https(club["source_url"],club["host"])
    if p.hostname.removeprefix("www.")!=canonical.hostname.removeprefix("www."):
        raise ValueError("ARTICLE_CAPTURE_CLUB_HOST_CONFLICT")
    if (article.get("club_key")!=club["club_key"] or
        article.get("league")!=club["league"] or
        article.get("status")!="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED" or
        article.get("source_http_status")!=200):
        raise ValueError("LIVE_ARTICLE_CAPTURE_STATUS_OR_SCOPE")
    rawsha=article.get("body_sha256")
    if not isinstance(rawsha,str) or not _SHA.fullmatch(rawsha):
        raise ValueError("ARTICLE_CAPTURE_BODY_PIN")
    observed=article.get("observed_at_utc")
    when=int(time.time()) if now_utc is None else now_utc
    if (type(observed) is not int or type(when) is not int or
        not 0<observed<=when<=observed+600):
        raise ValueError("LIVE_ARTICLE_CAPTURE_CLOCK")
    root=_verify_folder(root or _ALLOWED_ROOT)
    identity=_packed(dict(club_key=club["club_key"],url=url,body_sha256=rawsha))
    filename="article-first-"+hashlib.sha256(identity).hexdigest()+".json"
    file=root/filename
    # Existing record MUST survive, preserving first observed date.
    if file.is_symlink():
        raise ValueError("ARTICLE_CAPTURE_RECEIPT_SYMLINK")
    if file.exists():
        existing=json.loads(file.read_text(encoding="utf-8"))
        verify_article_capture(existing)
        if (existing["club_key"]!=club["club_key"] or
            existing["source_url"]!=url or existing["body_sha256"]!=rawsha):
            raise ValueError("ARTICLE_CAPTURE_RECEIPT_IDENTITY_CONFLICT")
        return existing,file,False
    payload=dict(format=RECEIPT_FORMAT,club_key=club["club_key"],
                 source_url=url,body_sha256=rawsha,
                 observed_at_utc=observed,captured_at_utc=when)
    receipt=dict(payload,receipt_sha256=hashlib.sha256(_packed(payload)).hexdigest())
    encoded=_packed(receipt)
    if len(encoded)>2048:raise ValueError("ARTICLE_CAPTURE_RECEIPT_SIZE_LIMIT")
    try:
        with file.open("xb") as out:
            out.write(encoded)
        return receipt,file,True
    except FileExistsError:
        existing=json.loads(file.read_text(encoding="utf-8"))
        verify_article_capture(existing)
        if (existing["club_key"]!=club["club_key"] or
            existing["source_url"]!=url or existing["body_sha256"]!=rawsha):
            raise ValueError("ARTICLE_CAPTURE_CONCURRENT_IDENTITY_CONFLICT")
        return existing,file,False
