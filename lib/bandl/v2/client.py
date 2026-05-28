"""Deprecated: use ``bandl.client``."""

import warnings

warnings.warn(
    "bandl.v2.client is deprecated; use `from bandl import Bandl`",
    DeprecationWarning,
    stacklevel=2,
)

from bandl.client import Bandl, _Facet  # noqa: E402, F401

__all__ = ["Bandl", "_Facet"]
