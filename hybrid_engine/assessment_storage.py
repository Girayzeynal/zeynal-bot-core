"""Lossless bounded storage codecs; no numeric model or publication-policy change.

Legacy JSON path assets remain readable. Byte order and exact sample hashes
are preserved. Compression confers no external source authenticity.
"""
import base64
import gzip
import io
import json

import numpy as np
from core.team_identity import digest

NATIVE='LOSSLESS_NATIVE_RECEIPT_STORAGE_V1'
PATHS='COMPRESSED_INTEGER_JOINT_REGULATION_PATHS_V1'
DTYPES=('<i4','>i4','<i8','>i8')


def pack(raw):return base64.b64encode(gzip.compress(raw,mtime=0)).decode('ascii')


def unpack(value,limit):
    if type(value) is not str or len(value)>24*1024*1024:raise ValueError('CURRENT_ENCODED_ASSET_LIMIT')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value,validate=True))) as f:
        raw=f.read(limit+1)
    if len(raw)>limit:raise ValueError('CURRENT_COMPRESSED_ASSET_LIMIT')
    return raw


def native_asset(receipt):
    return dict(format=NATIVE,receipt_sha256=digest(receipt),
        content=pack(json.dumps(receipt,sort_keys=True,allow_nan=False).encode()))


def restore_native(asset):
    if asset.get('format')!=NATIVE:return asset
    receipt=json.loads(unpack(asset['content'],16*1024*1024))
    if digest(receipt)!=asset['receipt_sha256'] or digest(receipt['document'])!=receipt['document_sha256']:
        raise ValueError('CURRENT_NATIVE_RECEIPT_PIN')
    return receipt


def encode_paths(samples):
    if samples.dtype.str not in DTYPES or samples.shape!=(10000,4,2):
        raise ValueError('CURRENT_JOINT_PATH_SHAPE_OR_DTYPE')
    return dict(format=PATHS,dtype=samples.dtype.str,samples_b64=pack(samples.tobytes()))


def decode_paths(asset):
    if asset.get('dtype') not in DTYPES:raise ValueError('CURRENT_JOINT_PATH_DTYPE_OR_RANGE')
    dtype=np.dtype(asset['dtype'])
    if asset.get('format')==PATHS:
        raw=unpack(asset['samples_b64'],10000*4*2*dtype.itemsize)
        if len(raw)!=10000*4*2*dtype.itemsize:raise ValueError('CURRENT_JOINT_PATH_SHAPE')
        values=np.frombuffer(raw,dtype=dtype).reshape(10000,4,2)
    elif asset.get('format')=='INTEGER_JOINT_REGULATION_PATHS_V1':
        values=np.asarray(asset['samples'])
        if values.shape!=(10000,4,2) or not np.issubdtype(values.dtype,np.integer):
            raise ValueError('CURRENT_JOINT_PATH_SHAPE')
    else:raise ValueError('CURRENT_JOINT_PATH_FORMAT')
    if np.any(values<0) or np.any(values>1000):raise ValueError('CURRENT_JOINT_PATH_DTYPE_OR_RANGE')
    return values.astype(dtype,copy=False)
