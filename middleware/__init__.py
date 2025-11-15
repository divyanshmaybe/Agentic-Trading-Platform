"""Shared middleware package.

This package exposes the Python middleware modules that physically
live under the ``py`` subdirectory so that they can be imported using
``middleware.<module_name>`` consistently across services.
"""

from __future__ import annotations

import os

# Ensure Python also searches the ``middleware/py`` directory whenever
# ``middleware`` is imported. This keeps historical import paths working
# without forcing every consumer to reference the extra sub-package.
_PACKAGE_DIR = os.path.dirname(__file__)
_PY_SUBDIR = os.path.join(_PACKAGE_DIR, "py")

if os.path.isdir(_PY_SUBDIR) and _PY_SUBDIR not in __path__:
	__path__.append(_PY_SUBDIR)

__all__ = []

