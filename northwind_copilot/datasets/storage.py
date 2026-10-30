"""Local uploaded datasets live at ``{dataset_data_dir}/{dataset_id}.sqlite``."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from northwind_copilot.core.config import settings


def dataset_path(dataset_id: str) -> Path:
    """Return a dataset's path, rejecting traversal and the legacy tenant root."""
    if str(UUID(dataset_id)) != dataset_id:
        raise ValueError("Invalid dataset id.")
    root = Path(settings.dataset_data_dir).resolve()
    if "tenants" in root.parts:
        raise ValueError("Refusing legacy tenant data directory.")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{dataset_id}.sqlite"
    if path.is_symlink():
        raise ValueError("Dataset files must not be symlinks.")
    return path


def delete_dataset_file(dataset_id: str) -> None:
    """Remove one uploaded dataset file, if present."""
    dataset_path(dataset_id).unlink(missing_ok=True)
