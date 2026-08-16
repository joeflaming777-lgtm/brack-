"""
Tests for repository endpoints.
"""
import pytest
from httpx import AsyncClient, ASGITransport


class TestRepositories:
    async def _auth_headers(self, client: AsyncClient, username: str = "repouser") -> dict:
        await client.post("/api/v1/auth/register", json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password123",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "password123",
        })
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    async def test_create_repo(self, client: AsyncClient):
        headers = await self._auth_headers(client)
        resp = await client.post("/api/v1/repos", json={
            "name": "my-project",
            "description": "Test repository",
            "visibility": "private",
        }, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-project"
        assert data["slug"] == "my-project"
        assert data["visibility"] == "private"

    async def test_create_duplicate_repo(self, client: AsyncClient):
        headers = await self._auth_headers(client, "dupuser")
        await client.post("/api/v1/repos", json={"name": "dup-repo"}, headers=headers)
        resp = await client.post("/api/v1/repos", json={"name": "dup-repo"}, headers=headers)
        assert resp.status_code == 409

    async def test_list_repos(self, client: AsyncClient):
        headers = await self._auth_headers(client, "listuser")
        await client.post("/api/v1/repos", json={"name": "repo1"}, headers=headers)
        await client.post("/api/v1/repos", json={"name": "repo2"}, headers=headers)

        resp = await client.get("/api/v1/repos", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    async def test_private_repo_requires_auth(self, client: AsyncClient):
        headers = await self._auth_headers(client, "privateuser")
        await client.post("/api/v1/repos", json={
            "name": "secret-repo",
            "visibility": "private",
        }, headers=headers)

        # Anonymous access should fail
        resp = await client.get("/api/v1/repos/privateuser/secret-repo")
        assert resp.status_code == 404

    async def test_public_repo_accessible_anonymously(self, client: AsyncClient):
        headers = await self._auth_headers(client, "publicuser")
        await client.post("/api/v1/repos", json={
            "name": "public-repo",
            "visibility": "public",
        }, headers=headers)

        resp = await client.get("/api/v1/repos/publicuser/public-repo")
        assert resp.status_code == 200

    async def test_delete_repo(self, client: AsyncClient):
        headers = await self._auth_headers(client, "deleteuser")
        await client.post("/api/v1/repos", json={"name": "to-delete"}, headers=headers)

        resp = await client.delete("/api/v1/repos/deleteuser/to-delete", headers=headers)
        assert resp.status_code == 204

        resp2 = await client.get("/api/v1/repos/deleteuser/to-delete", headers=headers)
        assert resp2.status_code == 404

    async def test_create_repo_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/v1/repos", json={"name": "no-auth"})
        assert resp.status_code == 401
