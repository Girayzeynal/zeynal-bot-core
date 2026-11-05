"""Restore/replay in a clean directory and isolated Python child; not a new cloud VM."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def verify_clean_process(bundle):
    bundle=Path(bundle).resolve();repo=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='faz33-clean-restore-') as folder:
        root=Path(folder)/'source';root.mkdir()
        files=[]
        for directory,children,names in os.walk(repo):
            children[:]=[c for c in children if not c.startswith('.') and c!='__pycache__']
            files.extend((Path(directory)/n).relative_to(repo) for n in names if n.endswith('.py') and not (Path(directory)/n).is_symlink())
        for name in files:
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
        evidence='docs/evidence/faz33-official-season-20261105.json'
        (root/evidence).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/evidence,root/evidence)
        code="import sys,json;sys.path.insert(0,sys.argv[1]);import research_recovery;r=research_recovery.verify_bundle(sys.argv[2]);r['implementation_path']=research_recovery.__file__;print(json.dumps(r,sort_keys=True))"
        proc=subprocess.run([sys.executable,'-I','-c',code,str(root),str(bundle)],cwd=root,check=True,capture_output=True,text=True,timeout=120)
        report=json.loads(proc.stdout)
        if not Path(report['implementation_path']).is_relative_to(root):raise ValueError('restore imported original workspace implementation')
        return dict(status='CLEAN_PROCESS_RESTORE_VERIFIED',verification=report,
            new_process=True,clean_source_directory=True,new_codex_cloud_session_tested=False,
            external_uploaded=False,warning='Same managed machine; a new Codex Cloud runtime was not provisioned')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bundle');args=p.parse_args()
    print(json.dumps(verify_clean_process(args.bundle),sort_keys=True))
