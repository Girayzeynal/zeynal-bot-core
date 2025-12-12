# faz23_engine/__init__.py

# ⚠️ Faz13 import'ları burada direkt olmamalı.
#    Faz23 engine kendi içinde izole olmalı.

__all__ = [
    # FAZ-23 MAX
    "Faz23MaxConfig",
    "faz23_max_predict",
    "faz23_max_comment",
    "build_fusion_vector",
]

# Lazy yükleme
def Faz23MaxConfig(*args, **kwargs):
    from .faz23_max import Faz23MaxConfig as _C
    return _C(*args, **kwargs)

def faz23_max_predict(*args, **kwargs):
    from .faz23_max import faz23_max_predict
    return faz23_max_predict(*args, **kwargs)

def faz23_max_comment(*args, **kwargs):
    from .faz23_max import faz23_max_comment
    return faz23_max_comment(*args, **kwargs)

def build_fusion_vector(*args, **kwargs):
    from .faz23_max import build_fusion_vector
    return build_fusion_vector(*args, **kwargs)
