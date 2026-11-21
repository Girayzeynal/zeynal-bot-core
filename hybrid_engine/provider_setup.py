"""Explicit local-only import of data keys; never source an application .env.

Only the two data-provider allowlists are parsed. Other entries, including
Telegram tokens, are ignored. The source is never modified and no Fly secret
is accessed. Key values are never returned in reports or exception messages.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile

from hybrid_engine.provider_access import KEYS, PRIVATE_FILE, credentials, preflight


def import_local(source, destination):
    source=Path(source).absolute();destination=Path(destination).absolute()
    if source.resolve()==destination.resolve():
        raise ValueError('SOURCE_AND_TEST_CONFIG_MUST_DIFFER')
    info=source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>65536:
        raise ValueError('LOCAL_SOURCE_OWNER_TYPE_OR_SIZE_REFUSED')
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        opened=os.fstat(stream.fileno())
        if opened.st_dev!=info.st_dev or opened.st_ino!=info.st_ino:
            raise ValueError('LOCAL_SOURCE_CHANGED')
        body=stream.read(65537)
    if len(body)>65536:
        raise ValueError('LOCAL_SOURCE_SIZE_LIMIT')
    allowed={n for names in KEYS.values() for n in names};selected={}
    for line in body.splitlines():
        line=line.strip()
        if line.startswith('export '):line=line[7:].lstrip()
        name,sep,value=line.partition('=');name=name.strip()
        if not sep or name not in allowed:
            continue
        try:parts=shlex.split(value,comments=True,posix=True)
        except ValueError:
            raise ValueError('LOCAL_PROVIDER_VALUE_NOT_LITERAL') from None
        if not parts:continue
        if (len(parts)!=1 or len(parts[0])>512 or any(ord(c)<33 for c in parts[0]) or
                any(marker in parts[0] for marker in ('${','$(','`'))):
            raise ValueError('LOCAL_PROVIDER_VALUE_NOT_LITERAL')
        if name in selected and selected[name]!=parts[0]:
            raise ValueError('CONFLICTING_LOCAL_PROVIDER_DEFINITIONS')
        selected[name]=parts[0]
    imported={}
    for provider,names in KEYS.items():
        options={selected[n] for n in names if selected.get(n)}
        if len(options)>1:raise ValueError('CONFLICTING_LOCAL_PROVIDER_ALIASES')
        if options:imported[provider]=options.pop()
    if destination.is_symlink():
        raise ValueError('LOCAL_SOURCE_OWNER_TYPE_OR_SIZE_REFUSED')
    before=None
    if destination.exists():
        fd=os.open(destination,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:before=stream.read(8193)
        if len(before)>8192:raise ValueError('LOCAL_SOURCE_OWNER_TYPE_OR_SIZE_REFUSED')
    existing=credentials({},destination)
    if before is not None and destination.read_bytes()!=before:
        raise ValueError('TEST_PROVIDER_CONFIG_CHANGED_CONCURRENTLY')
    if any(p in existing and existing[p]!=v for p,v in imported.items()):
        raise ValueError('EXISTING_TEST_PROVIDER_KEY_CONFLICT_UNCHANGED')
    merged={**existing,**imported}
    status='NO_PROVIDER_KEYS_FOUND_IN_LOCAL_SOURCE'
    if imported:
        status='ALREADY_CONFIGURED_UNCHANGED' if merged==existing else 'TEST_PROVIDER_KEYS_IMPORTED'
    if merged!=existing:
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=destination.parent,prefix='.test-provider-',delete=False) as f:
                temporary=Path(f.name);os.fchmod(f.fileno(),0o600)
                for p in sorted(merged):f.write(KEYS[p][0]+'='+merged[p]+'\n')
                f.flush();os.fsync(f.fileno())
            if before is None:
                os.link(temporary,destination)
            else:
                if destination.is_symlink() or destination.read_bytes()!=before:
                    raise ValueError('TEST_PROVIDER_CONFIG_CHANGED_CONCURRENTLY')
                os.replace(temporary,destination)
            fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    return dict(status=status,providers={p:('CONFIGURED_NOT_TESTED' if p in merged else
        'KEY_NOT_FOUND_IN_LOCAL_SOURCE_OR_TEST_CONFIG') for p in KEYS},
        source_changed=False,production_changed=False,api_requests_made=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-env',required=True,help='Explicit existing local env file; no shell evaluation.')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        result=import_local(args.from_env,Path.home()/PRIVATE_FILE)
    except Exception as exc:
        code=str(exc)
        allowed={'SOURCE_AND_TEST_CONFIG_MUST_DIFFER','LOCAL_SOURCE_OWNER_TYPE_OR_SIZE_REFUSED',
            'LOCAL_SOURCE_CHANGED','LOCAL_SOURCE_SIZE_LIMIT','LOCAL_PROVIDER_VALUE_NOT_LITERAL',
            'CONFLICTING_LOCAL_PROVIDER_DEFINITIONS','CONFLICTING_LOCAL_PROVIDER_ALIASES',
            'EXISTING_TEST_PROVIDER_KEY_CONFLICT_UNCHANGED','TEST_PROVIDER_CONFIG_CHANGED_CONCURRENTLY'}
        reason=code if code in allowed else 'LOCAL_PROVIDER_SOURCE_NOT_ACCESSIBLE_OR_PRIVATE_CONFIG_INVALID'
        print(json.dumps(dict(status='IMPORT_BLOCKED',reason=reason,api_requests_made=0,production_changed=False)))
        return 2
    print(json.dumps(result))
    if args.check:preflight(check=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
