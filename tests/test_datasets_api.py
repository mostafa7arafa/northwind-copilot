"""Integration tests for the dataset management API (local workspace)."""

from __future__ import annotations


def _csv() -> bytes:
    return b"Region,Sales\nNorth,100\nSouth,220\n"


async def _upload(client, data=None, filename="data.csv", name="My data"):
    return await client.post(
        "/api/datasets",
        files={"file": (filename, data or _csv(), "text/csv")},
        data={"name": name},
    )


class TestUpload:
    async def test_upload_works_without_login(self, local_client):
        resp = await _upload(local_client)
        assert resp.status_code == 201

    async def test_upload_csv_creates_ready_dataset(self, local_client):
        resp = await _upload(local_client)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ready"
        assert body["row_count"] == 2
        assert body["table_count"] == 1
        assert "Table data" in body["schema_summary"]

    async def test_unsupported_type_rejected(self, local_client):
        resp = await _upload(local_client, data=b"{}", filename="x.json")
        assert resp.status_code == 400

    async def test_bad_sqlite_rejected(self, local_client):
        resp = await _upload(local_client, data=b"not a db", filename="x.sqlite")
        assert resp.status_code == 400


class TestListGetContextDelete:
    async def test_list_returns_own_datasets(self, local_client):
        await _upload(local_client, name="One")
        resp = await local_client.get("/api/datasets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "One"

    async def test_edit_business_context(self, local_client):
        ds_id = (await _upload(local_client)).json()["id"]
        resp = await local_client.put(
            f"/api/datasets/{ds_id}/context",
            json={"business_context": "Sales are in USD."},
        )
        assert resp.status_code == 200
        assert resp.json()["business_context"] == "Sales are in USD."

    async def test_delete_removes_dataset(self, local_client):
        ds_id = (await _upload(local_client)).json()["id"]
        assert (await local_client.delete(f"/api/datasets/{ds_id}")).status_code == 204
        assert (await local_client.get(f"/api/datasets/{ds_id}")).status_code == 404


class TestUploadSafety:
    async def test_empty_file_rejected(self, local_client):
        response = await local_client.post(
            "/api/datasets", files={"file": ("empty.csv", b"", "text/csv")}
        )
        assert response.status_code == 400
        assert (await local_client.get("/api/datasets")).json() == []

    async def test_25mb_cap_retained_for_upload_and_append(self, local_client):
        from northwind_copilot.datasets.router import _MAX_UPLOAD_BYTES

        assert _MAX_UPLOAD_BYTES == 25 * 1024 * 1024
        ds_id = (await _upload(local_client)).json()["id"]
        for route in ("/api/datasets", f"/api/datasets/{ds_id}/files"):
            response = await local_client.post(
                route,
                files={
                    "file": ("large.csv", b"x" * (_MAX_UPLOAD_BYTES + 1), "text/csv")
                },
            )
            assert response.status_code == 413
        assert (await local_client.get(f"/api/datasets/{ds_id}")).json()[
            "row_count"
        ] == 2

    async def test_more_than_trial_quota_can_be_uploaded(self, local_client):
        for i in range(4):
            assert (await _upload(local_client, name=f"Dataset {i}")).status_code == 201
        assert len((await local_client.get("/api/datasets")).json()) == 4

    async def test_missing_dataset_is_404(self, local_client):
        for method, route, kwargs in (
            ("GET", "/api/datasets/missing", {}),
            ("DELETE", "/api/datasets/missing", {}),
            ("POST", "/api/datasets/missing/query", {"json": {"sql": "SELECT 1"}}),
            (
                "POST",
                "/api/datasets/missing/files",
                {"files": {"file": ("more.csv", _csv(), "text/csv")}},
            ),
        ):
            assert (
                await local_client.request(method, route, **kwargs)
            ).status_code == 404

    async def test_delete_removes_file_and_unlinks_saved_conversation(
        self, local_client
    ):
        from pathlib import Path

        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import (
            Conversation,
            Dataset,
            GoldenExample,
        )

        ds_id = (await _upload(local_client)).json()["id"]
        async with get_sessionmaker()() as session:
            path = Path((await session.get(Dataset, ds_id)).file_path)
            convo = Conversation(dataset_id=ds_id)
            session.add(convo)
            session.add(GoldenExample(dataset_id=ds_id, question="Q", sql="SELECT 1"))
            await session.commit()
            convo_id = convo.id
        assert path.is_file()
        assert (await local_client.delete(f"/api/datasets/{ds_id}")).status_code == 204
        assert not path.exists()
        detail = (await local_client.get(f"/api/conversations/{convo_id}")).json()
        assert detail["dataset_id"] is None
