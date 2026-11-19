"""Explicit read-only import from the one authorized, already running Fly VM.

SSH output is captured privately and never printed. No start, update, deploy,
secret-set, filesystem write or database access occurs on Fly. Staged values
cannot be recovered this way and are never activated.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

from hybrid_engine.provider_access import PRIVATE_FILE, preflight
from hybrid_engine.provider_setup import import_local

APP='zeynal-bot-core'
MACHINE='830932f77d2598'
MARKER='ZEYNAL_PRIVATE_PROVIDER_TRANSFER_V1:'
NAMES=('ODDS_API_KEY','API_SPORTS_KEY')

# A read-only program. No values are embedded in command arguments or logs.
REMOTE='''import os,json,base64
names=("ODDS_API_KEY","API_SPORTS_KEY")
sources=[{n:os.environ[n] for n in names if n in os.environ}]
paths=["/proc/1/environ"]
for pid in sorted(p for p in os.listdir("/proc") if p.isdigit())[:128]:
 try:
  with open("/proc/"+pid+"/cmdline","rb") as f: args=f.read(8192).split(b"\\0")
  if any(a.rsplit(b"/",1)[-1]==b"main.py" for a in args): paths.append("/proc/"+pid+"/environ")
 except OSError: pass
for path in set(paths):
 try:
  with open(path,"rb") as f: raw=f.read(65536)
  row={}
  for entry in raw.split(b"\\0"):
   k,sep,v=entry.partition(b"=")
   if sep and k.decode("utf-8","ignore") in names: row[k.decode()]=v.decode()
  sources.append(row)
 except (OSError,UnicodeError): pass
result={}
for name in names:
 values={s[name] for s in sources if s.get(name)}
 if len(values)>1: raise SystemExit("CONFLICTING_RUNNING_PROVIDER_VALUES")
 if values: result[name]=values.pop()
body=json.dumps(result,separators=(",",":")).encode()
print("ZEYNAL_PRIVATE_PROVIDER_TRANSFER_V1:"+base64.b64encode(body).decode())
'''


def transfer(destination,*,runner=subprocess.run,fly=None):
    executable=fly or shutil.which('fly') or shutil.which('flyctl')
    if not executable:raise ValueError('FLY_CLI_NOT_AVAILABLE')
    def call(args):
        try:
            r=runner([executable,*args],stdin=subprocess.DEVNULL,capture_output=True,timeout=25,check=False)
        except Exception:
            raise ValueError('READ_ONLY_FLY_COMMAND_FAILED') from None
        if r.returncode or len(r.stdout)>128*1024 or len(r.stderr)>128*1024:
            raise ValueError('READ_ONLY_FLY_COMMAND_FAILED')
        return r.stdout.decode('utf-8','replace')
    try:
        machines=json.loads(call(['machine','list','--app',APP,'--json']))
    except (TypeError,json.JSONDecodeError):
        raise ValueError('RUNNING_MACHINE_STATE_NOT_PROVEN') from None
    if not isinstance(machines,list):raise ValueError('RUNNING_MACHINE_STATE_NOT_PROVEN')
    found=[m for m in machines if m.get('id')==MACHINE]
    if len(found)!=1 or found[0].get('state')!='started':
        raise ValueError('TARGET_MACHINE_NOT_ALREADY_STARTED_NO_START_ATTEMPTED')
    command=shlex.join(['python','-B','-c',REMOTE])
    text=call(['ssh','console','--app',APP,'--machine',MACHINE,'--command',command])
    packets=[line[len(MARKER):] for line in text.splitlines() if line.startswith(MARKER)]
    if len(packets)!=1 or len(packets[0])>8192:
        raise ValueError('PRIVATE_FLY_TRANSFER_PACKET_NOT_RECEIVED')
    try:values=json.loads(base64.b64decode(packets[0],validate=True))
    except Exception:raise ValueError('INVALID_PRIVATE_FLY_TRANSFER_PACKET') from None
    if (not isinstance(values,dict) or not set(values)<=set(NAMES) or
            any(not isinstance(v,str) or not 1<=len(v)<=512 or any(ord(c)<33 for c in v) for v in values.values())):
        raise ValueError('PRIVATE_FLY_TRANSFER_ALLOWLIST')
    if not values:
        return dict(status='NO_PROVIDER_KEYS_READABLE_FROM_RUNNING_MACHINE',api_requests_made=0,
                    production_changed=False,staged_secrets_activated=False)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',prefix='.provider-transfer-',delete=False) as f:
            temporary=Path(f.name);os.fchmod(f.fileno(),0o600)
            for name in NAMES:
                if name in values:f.write(name+'='+shlex.quote(values[name])+'\n')
        result=import_local(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    result.update(source='ALREADY_RUNNING_FLY_MACHINE_ENVIRONMENT_ONLY',machine=MACHINE,
                  staged_secrets_activated=False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:result=transfer(Path.home()/PRIVATE_FILE)
    except Exception as exc:
        codes={'FLY_CLI_NOT_AVAILABLE','READ_ONLY_FLY_COMMAND_FAILED','RUNNING_MACHINE_STATE_NOT_PROVEN',
            'TARGET_MACHINE_NOT_ALREADY_STARTED_NO_START_ATTEMPTED','PRIVATE_FLY_TRANSFER_PACKET_NOT_RECEIVED',
            'INVALID_PRIVATE_FLY_TRANSFER_PACKET','PRIVATE_FLY_TRANSFER_ALLOWLIST',
            'EXISTING_TEST_PROVIDER_KEY_CONFLICT_UNCHANGED'}
        reason=str(exc) if str(exc) in codes else 'PRIVATE_TRANSFER_OR_LOCAL_CONFIG_REFUSED'
        print(json.dumps(dict(status='IMPORT_BLOCKED',reason=reason,production_changed=False)))
        return 2
    print(json.dumps(result))
    if args.check:preflight(check=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
