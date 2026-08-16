"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import Base, get_db
from app.config.settings import get_settings


TEST_DB_URL = "postgresql+asyncpg://brack:brackpassword@localhost:5432/brack_test"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSession() as session:
        yield session


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "testuser"
        assert "password" not in data

    async def test_register_duplicate_username(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "securepass123",
        })
        resp = await client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "other@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 409

    async def test_register_invalid_username(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "-invalid",
            "email": "test@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 422

    async def test_register_short_password(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        # Register first
        await client.post("/api/v1/auth/register", json={
            "username": "loginuser",
            "email": "login@example.com",
            "password": "password123",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "username": "loginuser",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "username": "loginuser2",
            "email": "login2@example.com",
            "password": "password123",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "username": "loginuser2",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    async def test_me_endpoint(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "username": "meuser",
            "email": "me@example.com",
            "password": "password123",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "username": "meuser",
            "password": "password123",
        })
        token = login_resp.json()["access_token"]

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "meuser"

    async def test_me_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestPersonalAccessTokens:
    async def _get_token(self, client: AsyncClient) -> str:
        await client.post("/api/v1/auth/register", json={
            "username": "tokenuser",
            "email": "token@example.com",
            "password": "password123",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "username": "tokenuser",
            "password": "password123",
        })
        return resp.json()["access_token"]

    async def test_create_and_use_pat(self, client: AsyncClient):
        jwt = await self._get_token(client)
        headers = {"Authorization": f"Bearer {jwt}"}

        # Create PAT
        resp = await client.post("/api/v1/auth/tokens", json={
            "name": "My CLI Token",
            "scopes": ["repo:read", "repo:write"],
        }, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["token"].startswith("brk_")
        pat = data["token"]

        # Use PAT to access /me
        resp2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {pat}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["username"] == "tokenuser"
