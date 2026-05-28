"""Convert Pydantic models to pandas DataFrames."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from pydantic import BaseModel


def models_to_dataframe(rows: Sequence[BaseModel]) -> pd.DataFrame:
    """Serialize a sequence of Pydantic models into a DataFrame."""
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([r.model_dump() for r in rows])
