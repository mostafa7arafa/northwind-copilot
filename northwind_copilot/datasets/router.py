"""Dataset management API: upload, list, inspect, edit context, delete.

Uploads are ingested synchronously with a fixed 25MB safety ceiling.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.core.config import settings
from northwind_copilot.datasets import ingest as ingest_mod
from northwind_copilot.datasets import storage
from northwind_copilot.datasets.schema_summary import generate_summary
from northwind_copilot.persistence.db import get_session
from northwind_copilot.persistence.models import Dataset
from northwind_copilot.web.security import rate_limit, require_access

router = APIRouter(
    prefix="/api/datasets", tags=["datasets"], dependencies=[Depends(require_access)]
)

# Hard ceiling on synchronous in-request ingestion to bound memory and latency.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_EXT_TO_SOURCE = {
    "csv": "csv",
    "tsv": "csv",
    "xlsx": "xlsx",
    "xls": "xlsx",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "db": "sqlite",
}


class DatasetOut(BaseModel):
    """Public view of a dataset."""

    id: str
    name: str
    source_type: str
    status: str
    row_count: int
    table_count: int
    schema_summary: str
    business_context: str
    error: str

    @classmethod
    def of(cls, d: Dataset) -> "DatasetOut":
        return cls(
            id=d.id,
            name=d.name,
            source_type=d.source_type,
            status=d.status,
            row_count=d.row_count,
            table_count=d.table_count,
            schema_summary=d.schema_summary,
            business_context=d.business_context,
            error=d.error,
        )


class ContextUpdate(BaseModel):
    """A business-context edit."""

    business_context: str = Field(max_length=settings.max_preferences_chars)


class QueryRequest(BaseModel):
    """A user-edited SQL statement to run against a dataset."""

    sql: str = Field(min_length=1, max_length=10_000)


def _source_type(filename: str) -> str:
    """Map an uploaded filename to a supported source type, or raise 400."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    source = _EXT_TO_SOURCE.get(ext)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Upload a CSV, Excel, or SQLite file.",
        )
    return source


async def _load_dataset(session: AsyncSession, dataset_id: str) -> Dataset:
    """Fetch a dataset from the local workspace."""
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return dataset


@router.post("", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Upload a file, ingest it into a local SQLite dataset, and return it."""
    source_type = _source_type(file.filename or "")
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty."
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File exceeds the upload size limit.",
        )
    dataset = Dataset(
        name=name.strip() or (file.filename or "dataset"),
        source_type=source_type,
        status="processing",
    )
    session.add(dataset)
    await session.flush()  # assign dataset.id

    dest = storage.dataset_path(dataset.id)
    try:
        result = ingest_mod.ingest(source_type, data, dest)
        dataset.file_path = str(dest)
        dataset.size_bytes = dest.stat().st_size
        dataset.row_count = result.row_count
        dataset.table_count = result.table_count
        dataset.schema_summary = generate_summary(dest)
        dataset.status = "ready"
    except ingest_mod.IngestError as exc:
        storage.delete_dataset_file(dataset.id)
        dataset.status = "failed"
        dataset.error = str(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return DatasetOut.of(dataset)


@router.post("/{dataset_id}/files", response_model=DatasetOut)
async def add_file(
    dataset_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Add another file's tables to an existing dataset (multi-file datasets).

    Each appended upload becomes more tables in the same local SQLite, so
    questions can join across files ("match sales.csv against targets.xlsx").
    Table names are de-conflicted, never replaced.
    """
    from pathlib import Path

    dataset = await _load_dataset(session, dataset_id)
    if dataset.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is not ready for more files.",
        )
    source_type = _source_type(file.filename or "")
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty."
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File exceeds the upload size limit.",
        )
    name_hint = (file.filename or "data").rsplit(".", 1)[0]
    path = Path(dataset.file_path)
    try:
        ingest_mod.append(source_type, data, path, name_hint=name_hint)
    except ingest_mod.IngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    finally:
        # True-up from the file, not arithmetic: a multi-sheet append that
        # failed partway must still leave the stored counts accurate.
        if path.exists():
            tables, rows = ingest_mod.dataset_stats(path)
            dataset.table_count = tables
            dataset.row_count = rows
            dataset.size_bytes = path.stat().st_size
            dataset.schema_summary = generate_summary(path)

    return DatasetOut.of(dataset)


@router.post("/{dataset_id}/query")
async def run_query(
    dataset_id: str,
    body: QueryRequest,
    session: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit),
) -> dict:
    """Run a user-edited SELECT against a dataset (SQL transparency).

    Goes through the exact same read-only + query-timeout + row-cap path as
    the agent's own result execution (``response.charting.run_sql``), so an
    edited query can't do anything the agent couldn't.
    """
    dataset = await _load_dataset(session, dataset_id)
    if dataset.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is still being prepared.",
        )
    from northwind_copilot.response.charting import run_sql

    table = run_sql(body.sql, dataset.file_path)
    if table is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The query couldn't be run. Only SELECT statements are "
            "allowed, and they must finish within the time budget.",
        )
    return table


@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    session: AsyncSession = Depends(get_session),
) -> list[DatasetOut]:
    """List workspace datasets, newest first."""
    rows = (
        await session.execute(select(Dataset).order_by(Dataset.created_at.desc()))
    ).scalars()
    return [DatasetOut.of(d) for d in rows]


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str,
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Return one dataset (incl. its schema summary)."""
    return DatasetOut.of(await _load_dataset(session, dataset_id))


@router.put("/{dataset_id}/context", response_model=DatasetOut)
async def update_context(
    dataset_id: str,
    body: ContextUpdate,
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Edit a dataset's business context (injected into the prompt)."""
    dataset = await _load_dataset(session, dataset_id)
    dataset.business_context = body.business_context.strip()
    return DatasetOut.of(dataset)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a dataset row and its SQLite file."""
    dataset = await _load_dataset(session, dataset_id)
    storage.delete_dataset_file(dataset.id)
    await session.delete(dataset)
