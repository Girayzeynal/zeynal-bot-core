"""
Initialize the FAZ16 engine package.

The original __init__.py attempted to load Faz16Engine from non-existent
submodules, causing ModuleNotFoundError at runtime. Since this repository
only provides the faz16_run_simulation function, this initializer exports
that function directly. A placeholder for Faz16Engine (set to None) is also
provided for backward compatibility with code that checks for its existence.
"""

from .faz16_simulation import faz16_run_simulation

# There is no Faz16Engine class in this package; provide None to avoid attribute errors
Faz16Engine = None

__all__ = ["faz16_run_simulation", "Faz16Engine"] 
