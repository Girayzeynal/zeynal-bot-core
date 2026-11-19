"""Optional bounded PDF extraction subprocess; never a status verification claim."""
import hashlib
import json
from pathlib import Path
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024*1024, 1024*1024))
    try:
        path = Path(sys.argv[1])
        if path.is_symlink() or not 8 <= path.stat().st_size <= 8*1024*1024:
            raise ValueError('PDF_PATH_OR_SIZE')
        body = path.read_bytes()
        from hybrid_engine.nba_injury_pdf_parser import extract_nba_injury_rows
        result = extract_nba_injury_rows(body, expected_sha256=hashlib.sha256(body).hexdigest())
        if len(result['rows']) > 500 or len(json.dumps(result)) > 512*1024:
            raise ValueError('PDF_ROW_BUDGET')
        result['worker_peak_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    except Exception as exc:
        result = dict(status='PDF_EXTRACTION_UNAVAILABLE', error_type=type(exc).__name__, rows=[],
                      extraction_verified=False)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
