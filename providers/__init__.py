# providers/__init__.py

from .espn_adapter import ESPNAdapter

PROVIDERS = {
    "ESPN": ESPNAdapter,
}

__all__ = ["PROVIDERS", "ESPNAdapter"] 
