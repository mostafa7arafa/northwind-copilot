"""Dataset management API: upload, list, inspect, edit context, delete.

Uploads are ingested synchronously (tier caps keep files small enough that this
is fine without a task queue). Every route is scoped to the caller's org, so one
tenant can never see or touch another's datasets.
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
from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.deps import RequestContext, current_org
from northwind_copilot.tenancy.models import Dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# v1 upload ceiling. Phase 1 entitlements replace this with a per-tier cap.
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


async def _load_owned(
    session: AsyncSession, dataset_id: str, ctx: RequestContext
) -> Dataset:
    """Fetch a dataset, enforcing that it belongs to the caller's org."""
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None or dataset.org_id != ctx.org_id:
        # Same 404 whether it doesn't exist or belongs to another tenant, so the
        # API never confirms the existence of another org's data.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return dataset


@router.post("", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Upload a file, ingest it into a per-tenant SQLite dataset, and return it."""
    source_type = _source_type(file.filename or "")
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty."
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the upload size limit.",
        )

    dataset = Dataset(
        org_id=ctx.org_id,
        name=name.strip() or (file.filename or "dataset"),
        source_type=source_type,
        status="processing",
    )
    session.add(dataset)
    await session.flush()  # assign dataset.id

    dest = storage.dataset_path(ctx.org_id, dataset.id)
    try:
        result = ingest_mod.ingest(source_type, data, dest)
        dataset.file_path = str(dest)
        dataset.size_bytes = dest.stat().st_size
        dataset.row_count = result.row_count
        dataset.table_count = result.table_count
        dataset.schema_summary = generate_summary(dest)
        dataset.status = "ready"
    except ingest_mod.IngestError as exc:
        storage.delete_dataset_file(ctx.org_id, dataset.id)
        dataset.status = "failed"
        dataset.error = str(exc)
        # Persist the failed row so the user can see why, then 400.
        await session.flush()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return DatasetOut.of(dataset)


@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> list[DatasetOut]:
    """List the caller org's datasets, newest first."""
    rows = (
        await session.execute(
            select(Dataset)
            .where(Dataset.org_id == ctx.org_id)
            .order_by(Dataset.created_at.desc())
        )
    ).scalars()
    return [DatasetOut.of(d) for d in rows]


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Return one dataset (incl. its schema summary)."""
    return DatasetOut.of(await _load_owned(session, dataset_id, ctx))


@router.put("/{dataset_id}/context", response_model=DatasetOut)
async def update_context(
    dataset_id: str,
    body: ContextUpdate,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> DatasetOut:
    """Edit a dataset's business context (injected into the prompt)."""
    dataset = await _load_owned(session, dataset_id, ctx)
    dataset.business_context = body.business_context.strip()
    return DatasetOut.of(dataset)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: str,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a dataset row and its SQLite file."""
    dataset = await _load_owned(session, dataset_id, ctx)
    storage.delete_dataset_file(ctx.org_id, dataset.id)
    await session.delete(dataset)
