"""Read-only import of hash-pinned archives; observation clocks are preserved."""
import hashlib
import json
from pathlib import Path
import subprocess
from nba_research_store import ResearchStore
from prospective_error_audit import read_only_ledger


def committed_json(relative):
    root=Path(__file__).resolve().parent;path=root/relative
    raw=path.read_bytes()
    committed=subprocess.check_output(['git','show','HEAD:'+str(relative)],cwd=root)
    if raw!=committed:raise ValueError('archive differs from committed evidence')
    return json.loads(raw),dict(path=str(path),file_sha256=hashlib.sha256(raw).hexdigest(),
                               evidence_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())


def import_legacy(store, *, raw_root=None, input_ledger=None):
    """FAZ30 periods, optional pinned Nov02 files, optional original BOS/MIL input.

    Missing raw files are explicit errors. This imports observations only and
    never creates prospective predictions or writes the source ledger.
    """
    counts={}
    data,ref=committed_json('docs/evidence/faz30-diagnostic-report-20261105.json')
    counts['FAZ30_36']=sum(store.ingest(r['payload']['original_summary'],r['payload']['source_observed_utc'],'ARCHIVED_SOURCE',ref)
                            for r in data['period_feature_layer']['records'])
    if raw_root is not None:
        root=Path(raw_root);index,ref=committed_json('docs/evidence/nba-real-validation-20261104.json')
        def pinned(name):
            path=root/name;raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            if sha!=index['source_file_sha256'][name]:raise ValueError('raw archive checksum mismatch: '+name)
            return json.loads(raw),dict(path=str(path),file_sha256=sha,index=ref)
        manifest,_=pinned('manifest.json');count=0
        for name in index['source_file_sha256']:
            if not name.endswith('.json') or not name[:-5].isascii() or not name[:-5].isdigit():continue
            raw,source=pinned(name)
            count+=int(store.ingest(raw,manifest['observed_at_utc'],'ARCHIVED_SOURCE',source))
        counts['ARCHIVED_NOV02_15']=count
    if input_ledger is not None:
        path=Path(input_ledger);before=hashlib.sha256(path.read_bytes()).hexdigest()
        inputs=read_only_ledger(path).load_prediction_inputs('NBA','401909924')
        if inputs is None:raise ValueError('original input snapshot missing')
        count=0
        for team in inputs['payload']['teams'].values():
            for record in team['records']:
                evidence=record.get('pace_evidence')
                if not evidence:continue
                p=evidence['snapshot']
                count+=int(store.ingest(p['summary'],p['observed_at_utc'],'ARCHIVED_SOURCE',
                    dict(path=str(path),file_sha256=before,input_sha256=inputs['sha256'])))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('source ledger changed during read')
        counts['ARCHIVED_BOS_MIL_14']=count
    return dict(inserted_by_source=counts,coverage=store.coverage())


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('database');p.add_argument('directory_manifest')
    p.add_argument('--raw-root');p.add_argument('--input-ledger');a=p.parse_args()
    directory=json.loads(Path(a.directory_manifest).read_text())['directory']['teams']
    print(json.dumps(import_legacy(ResearchStore(a.database,directory),raw_root=a.raw_root,input_ledger=a.input_ledger),sort_keys=True))
