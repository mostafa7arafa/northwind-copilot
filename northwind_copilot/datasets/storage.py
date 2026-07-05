"""Filesystem layout for per-tenant dataset files.

Each dataset is one SQLite file at
``{tenant_data_dir}/{org_id}/{dataset_id}.sqlite``. Keeping every org in its
own directory makes tenant isolation a filesystem fact (and a per-org disk
quota a single ``du``-style walk), not just an application-layer check.
"""

from __future__ import annotations

from pathlib import Path

from northwind_copilot.core.config import settings


def org_dir(org_id: str) -> Path:
    """Return (creating if needed) the directory holding an org's datasets."""
    path = Path(settings.tenant_data_dir) / org_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_path(org_id: str, dataset_id: str) -> Path:
    """Return the SQLite path for one dataset."""
    return org_dir(org_id) / f"{dataset_id}.sqlite"


def org_usage_bytes(org_id: str) -> int:
    """Return the total on-disk size of an org's dataset files."""
    directory = Path(settings.tenant_data_dir) / org_id
    if not directory.exists():
        return 0
    return sum(f.stat().st_size for f in directory.glob("*.sqlite") if f.is_file())


def delete_dataset_file(org_id: str, dataset_id: str) -> None:
    """Remove a dataset's SQLite file if it exists."""
    path = dataset_path(org_id, dataset_id)
    path.unlink(missing_ok=True)
