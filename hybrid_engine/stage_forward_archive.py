"""Stage a pinned read-only research capsule into a dedicated local registry.

Existing bytes are never overwritten. This neither enables a bot nor promotes a
model. The original publication clocks remain unchanged during copying.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from hybrid_engine.data import local_path
from hybrid_engine.forward_validation import ForwardRegistry

PACKET_SHA='83b7377a945e391039a84f3295586c155277bae78ba9a659272cfad105a2fafb'


def stage(packet,directory):
    source=local_path(packet);root=local_path(directory)
    if source.stat().st_size>4*1024*1024 or hashlib.sha256(source.read_bytes()).hexdigest()!=PACKET_SHA:
        raise ValueError('FORWARD_CAPSULE_TRUSTED_PIN')
    root.mkdir(parents=True,exist_ok=True)
    total=0;count=0;seen=set()
    with tarfile.open(source,'r:gz') as archive:
        for member in archive:
            path=Path(member.name)
            if (not member.isfile() or len(path.parts)!=2 or path.parts[0]!='forward-euroleague' or
                path.name in seen or path.suffix!='.json' or member.size>2*1024*1024):
                raise ValueError('FORWARD_CAPSULE_MEMBER')
            count+=1;total+=member.size;seen.add(path.name)
            if count>192 or total>32*1024*1024:raise ValueError('FORWARD_CAPSULE_BUDGET')
            target=local_path(root/path.name);raw=archive.extractfile(member).read()
            if target.exists():
                if target.read_bytes()!=raw:raise ValueError('FORWARD_CAPSULE_EXISTING_CONFLICT')
            else:
                with target.open('xb') as out:out.write(raw)
    registry=ForwardRegistry(root);records=registry.records()
    finals=sum(registry.outcome(r['payload']) is not None for r in records)
    return dict(directory=str(root),records=len(records),verified_finals=finals,files=count,
                original_publication_clocks_preserved=True,production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packet',required=True);p.add_argument('--directory',required=True)
    a=p.parse_args();print(json.dumps(stage(a.packet,a.directory)))


if __name__=='__main__':main()
