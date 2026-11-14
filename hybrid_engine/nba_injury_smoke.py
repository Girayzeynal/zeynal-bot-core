"""Offline NBA injury PDF smoke check; never publishes statuses or edits archives.

Usage:
  python -m hybrid_engine.nba_injury_smoke /path/to/report.pdf
Install optional dependency in the isolated test venv: pip install pdfplumber
"""
import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter

from hybrid_engine.nba_injury_pdf_parser import extract_nba_injury_rows

def inspect_pdf(path):
    file=Path(path)
    if not file.is_file():
        raise ValueError('REPORT_FILE_REQUIRED')
    if file.stat().st_size>8*1024*1024:
        raise ValueError('OVERSIZED_PDF_BYTES')
    data=file.read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    parsed=extract_nba_injury_rows(data,expected_sha256=digest)
    rows=parsed['rows']
    by_matchup=dict(sorted(Counter(row['matchup'] for row in rows).items()))
    by_status=dict(sorted(Counter(row['status'] for row in rows).items()))
    return dict(sha256=digest,byte_count=len(data),
                by_matchup=by_matchup,by_status=by_status,
                status=parsed['status'],parsed_rows=len(parsed['rows']),
                rejected_rows=parsed['rejected_count'],
                extraction_verified=False,roster_verified=False,
                telegram_delivery_verified=False)

def main():
    parser=argparse.ArgumentParser(description='Offline research PDF structure check')
    parser.add_argument('pdf_path')
    parser.add_argument('--brief',action='store_true',help='Print compact one-line test result')
    args=parser.parse_args()
    result=inspect_pdf(args.pdf_path)
    if args.brief:
        print('PDF_PARSE={} rows={} rejected={} games={} statuses={} roster_verified={} telegram_verified={}'.format(
            'PASS' if result['parsed_rows'] else 'FAIL',result['parsed_rows'],
            result['rejected_rows'],json.dumps(result['by_matchup'],sort_keys=True),
            json.dumps(result['by_status'],sort_keys=True),
            result['roster_verified'],result['telegram_delivery_verified']))
    else:
        print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
