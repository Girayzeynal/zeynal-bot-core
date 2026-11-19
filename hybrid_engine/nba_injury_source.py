"""NBA official injury-report URL gate; no network or PDF extraction.

Use only with a separately fetched, hash-pinned PDF receipt and independently
verified row extraction. A filename is not proof of report contents.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

_PATTERN = re.compile(r'^/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf$')

def official_nba_injury_report_reference(url, *, retrieved_at_utc, prediction_utc):
    if not isinstance(url,str):
        raise ValueError('OFFICIAL_REPORT_URL_REQUIRED')
    parsed=urlparse(url)
    match=_PATTERN.fullmatch(parsed.path)
    if (parsed.scheme!='https' or parsed.netloc!='ak-static.cms.nba.com' or
            parsed.query or parsed.fragment or match is None):
        raise ValueError('UNRECOGNIZED_OFFICIAL_NBA_REPORT_URL')
    day,hour,minute,ampm=match.groups()
    hour=int(hour);minute=int(minute)
    if not 1<=hour<=12 or minute>59:
        raise ValueError('INVALID_REPORT_CLOCK')
    hour=(hour%12)+(12 if ampm=='PM' else 0)
    from zoneinfo import ZoneInfo
    report_time=datetime.fromisoformat(day).replace(hour=hour,minute=minute,tzinfo=ZoneInfo('America/New_York'))
    report_utc=int(report_time.astimezone(timezone.utc).timestamp())
    if (type(retrieved_at_utc) is not int or type(prediction_utc) is not int or
            not 0<report_utc<=retrieved_at_utc<=prediction_utc):
        raise ValueError('REPORT_NOT_AVAILABLE_BEFORE_PREDICTION')
    return dict(status='OFFICIAL_URL_AND_CLOCK_VERIFIED_CONTENT_NOT_PARSED',
                source_url=url,report_timestamp_utc=report_utc,
                retrieved_at_utc=retrieved_at_utc,
                player_status_records=[],roster_verified=False,
                extraction_verified=False)
