"""Owner-only recovery bundle; no off-machine upload or persistence guarantee."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
from faz25 import backup


def make_bundle(databases,destination,source_version):
    destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        root=Path(folder);manifest=dict(schema_version=1,source_version=source_version,files={},external_uploaded=False)
        for name,path in databases.items():
            if Path(name).name!=name or not name.endswith('.sqlite'):raise ValueError('safe SQLite basenames only')
            info=backup(path,root/name);manifest['files'][name]=info['sha256']
        (root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
        temporary=root/'recovery.tar.gz'
        with tarfile.open(temporary,'w:gz') as archive:
            archive.add(root/'manifest.json',arcname='manifest.json')
            for name in manifest['files']:archive.add(root/name,arcname=name)
        os.chmod(temporary,0o600);os.link(temporary,destination)
    return dict(path=str(destination),sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),external_uploaded=False)


def verify_bundle(path):
    with tarfile.open(path,'r:gz') as archive:
        members=archive.getmembers()
        if any(not m.isfile() or Path(m.name).name!=m.name for m in members):raise ValueError('unsafe archive entry')
        if len({m.name for m in members})!=len(members):raise ValueError('duplicate archive name')
        manifest=json.load(archive.extractfile('manifest.json'))
        if set(m.name for m in members)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('unexpected backup contents')
        reports=[]
        with tempfile.TemporaryDirectory() as folder:
            for name,sha in manifest['files'].items():
                if Path(name).name!=name or not name.endswith('.sqlite'):raise ValueError('unsafe manifest filename')
                raw=archive.extractfile(name).read()
                if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('backup checksum mismatch')
                restored=Path(folder)/name;restored.write_bytes(raw);os.chmod(restored,0o600)
                with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('SQLite restore integrity failure')
                    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'faz33_cuts' in tables:
                    from prospective_cuts import inspect
                    audited=inspect(restored);audited.pop('examples',None)
                    reports.append(dict(name=name,integrity='ok',prospective_cut_audit=audited))
                elif 'observations' in tables and 'metadata' in tables:
                    from nba_research_store import ResearchStore
                    store=object.__new__(ResearchStore);store.path=str(restored)
                    with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as db:
                        store.team_ids=set(json.loads(db.execute("SELECT value FROM metadata WHERE key='team_ids'").fetchone()[0]))
                    reports.append(dict(name=name,integrity='ok',research_coverage=store.coverage()))
                elif 'faz24_stages' in tables:
                    from prospective_error_audit import audit
                    replay=audit([str(restored)])
                    reports.append(dict(name=name,integrity='ok',verified_cohorts=len(replay['cohorts']),original_predictions=replay['distinct_fixtures']))
                else:reports.append(dict(name=name,integrity='ok',tables=sorted(tables)))
    return dict(status='RESTORE_VERIFIED_LOCALLY',files=reports,cloud_session_replacement_tested=False,
                external_uploaded=False,source_version=manifest['source_version'])
