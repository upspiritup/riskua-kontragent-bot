from __future__ import annotations

import json
from pathlib import Path

from app.models.company_lookup import CompanyLookupResult


DEFAULT_CHECKS_DIR = Path("data/checks")


def save_check_result(
    result: CompanyLookupResult,
    telegram_user_id: int | None = None,
    base_dir: Path = DEFAULT_CHECKS_DIR,
) -> Path:
    user_id = telegram_user_id if telegram_user_id is not None else result.telegram_user_id
    user_folder = str(user_id) if user_id is not None else "anonymous"
    target_dir = base_dir / user_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    result_to_save = result.model_copy(update={"telegram_user_id": user_id})
    target_path = target_dir / f"{result_to_save.check_id}.json"
    temp_path = target_dir / f".{result_to_save.check_id}.tmp"

    payload = result_to_save.model_dump(mode="json")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(target_path)
    return target_path
