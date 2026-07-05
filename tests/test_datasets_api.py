"""Integration tests for the dataset management API (hosted mode)."""

from __future__ import annotations


def _csv() -> bytes:
    return b"Region,Sales\nNorth,100\nSouth,220\n"


async def _signup(client, email):
    return await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "name": "T"},
    )


async def _upload(client, data=None, filename="data.csv", name="My data"):
    return await client.post(
        "/api/datasets",
        files={"file": (filename, data or _csv(), "text/csv")},
        data={"name": name},
    )


class TestUpload:
    async def test_upload_requires_auth(self, hosted_client):
        resp = await _upload(hosted_client)
        assert resp.status_code == 401

    async def test_upload_csv_creates_ready_dataset(self, hosted_client):
        await _signup(hosted_client, "a@x.com")
        resp = await _upload(hosted_client)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ready"
        assert body["row_count"] == 2
        assert body["table_count"] == 1
        assert "Table data" in body["schema_summary"]

    async def test_unsupported_type_rejected(self, hosted_client):
        await _signup(hosted_client, "b@x.com")
        resp = await _upload(hosted_client, data=b"{}", filename="x.json")
        assert resp.status_code == 400

    async def test_bad_sqlite_rejected(self, hosted_client):
        await _signup(hosted_client, "c@x.com")
        resp = await _upload(hosted_client, data=b"not a db", filename="x.sqlite")
        assert resp.status_code == 400


class TestListGetContextDelete:
    async def test_list_returns_own_datasets(self, hosted_client):
        await _signup(hosted_client, "d@x.com")
        await _upload(hosted_client, name="One")
        resp = await hosted_client.get("/api/datasets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "One"

    async def test_edit_business_context(self, hosted_client):
        await _signup(hosted_client, "e@x.com")
        ds_id = (await _upload(hosted_client)).json()["id"]
        resp = await hosted_client.put(
            f"/api/datasets/{ds_id}/context",
            json={"business_context": "Sales are in USD."},
        )
        assert resp.status_code == 200
        assert resp.json()["business_context"] == "Sales are in USD."

    async def test_delete_removes_dataset(self, hosted_client):
        await _signup(hosted_client, "f@x.com")
        ds_id = (await _upload(hosted_client)).json()["id"]
        assert (await hosted_client.delete(f"/api/datasets/{ds_id}")).status_code == 204
        assert (await hosted_client.get(f"/api/datasets/{ds_id}")).status_code == 404


class TestTenantIsolation:
    async def test_one_org_cannot_read_anothers_dataset(self, hosted_client):
        # Org A uploads a dataset.
        await _signup(hosted_client, "owner@x.com")
        ds_id = (await _upload(hosted_client)).json()["id"]
        hosted_client.cookies.clear()

        # Org B (a different account) must not be able to fetch, edit, or delete it.
        await _signup(hosted_client, "intruder@x.com")
        assert (await hosted_client.get(f"/api/datasets/{ds_id}")).status_code == 404
        assert (
            await hosted_client.put(
                f"/api/datasets/{ds_id}/context",
                json={"business_context": "hax"},
            )
        ).status_code == 404
        assert (await hosted_client.delete(f"/api/datasets/{ds_id}")).status_code == 404
        # And B's own dataset list stays empty.
        assert (await hosted_client.get("/api/datasets")).json() == []
