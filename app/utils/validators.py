from __future__ import annotations

import re


EDRPOU_PATTERN = re.compile(r"^[0-9]{8}$")


def is_valid_edrpou(value: str) -> bool:
    return EDRPOU_PATTERN.fullmatch((value or "").strip()) is not None
