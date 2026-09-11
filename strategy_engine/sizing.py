from __future__ import annotations

from typing import Literal, TypeVar

import numpy as np
import pandas as pd


QuantityMode = Literal["fractional", "whole_contracts"]
PositionLike = TypeVar("PositionLike", pd.Series, pd.DataFrame)


def size_contracts(raw_targets: PositionLike, mode: QuantityMode) -> PositionLike:
    """Apply a declared contract-quantity convention to target positions.

    Whole-contract targets are truncated toward zero. That makes rounding
    conservative: it cannot increase absolute notional beyond the raw target.
    """

    if mode == "fractional":
        return raw_targets.copy()
    if mode == "whole_contracts":
        return raw_targets.apply(np.trunc) if isinstance(raw_targets, pd.DataFrame) else raw_targets.map(np.trunc)
    raise ValueError(f"Unsupported quantity mode: {mode}")


def sizing_contract(mode: QuantityMode) -> dict[str, object]:
    if mode == "whole_contracts":
        return {
            "mode": mode,
            "quantity_unit": "exchange contracts",
            "rounding": "toward_zero",
            "executable_quantity": True,
        }
    return {
        "mode": mode,
        "quantity_unit": "fractional research units",
        "rounding": None,
        "executable_quantity": False,
    }
