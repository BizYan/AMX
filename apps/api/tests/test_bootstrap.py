"""Bootstrap Tests

Tests for the bootstrap admin user creation functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import hash_password, verify_password, create_access_token, decode_token


class TestPasswordHashing:
    """Tests for password hashing functionality."""

    def test_hash_password_returns_string(self):
        """Test that hash_password returns a string."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert isinstance(hashed, str)
        assert hashed != password

    def test_hash_password_different_each_time(self):
        """Test that hash_password produces different hashes for same password."""
        password = "test_password_123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2  # Different due to salt

    def test_verify_password_correct(self):
        """Test that verify_password returns True for correct password."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that verify_password returns False for incorrect password."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert verify_password("wrong_password", hashed) is False

    def test_hash_and_verify_roundtrip(self):
        """Test complete hash/verify roundtrip."""
        password = "my_secure_password_!@#$%"
        hashed = hash_password(password)
        assert verify_password(password, hashed)
        assert verify_password(password.upper()[: -1], hashed) is False


class TestJWTTokens:
    """Tests for JWT token creation and verification."""

    def test_create_access_token_returns_string(self):
        """Test that create_access_token returns a JWT string."""
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test_secret_key_12345"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30

            token = create_access_token({"sub": "user123"})
            assert isinstance(token, str)
            assert len(token) > 20  # JWT should be reasonably long

    def test_create_access_token_with_custom_expiry(self):
        """Test token creation with custom expiration."""
        from datetime import timedelta

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test_secret_key_12345"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30

            token = create_access_token(
                {"sub": "user123"},
                expires_delta=timedelta(hours=1),
            )
            assert isinstance(token, str)

    def test_decode_token_valid(self):
        """Test decoding a valid token."""
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test_secret_key_12345"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30

            token = create_access_token({"sub": "user123"})
            decoded = decode_token(token)
            assert decoded["sub"] == "user123"
            assert "exp" in decoded
            assert "iat" in decoded

    def test_decode_token_invalid(self):
        """Test decoding an invalid token raises error."""
        from jose import JWTError

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test_secret_key_12345"
            mock_settings.JWT_ALGORITHM = "HS256"

            with pytest.raises(JWTError):
                decode_token("invalid.token.here")

    def test_token_contains_required_claims(self):
        """Test that created tokens contain all required claims."""
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test_secret_key_12345"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30

            token = create_access_token({"sub": "user123", "role": "admin"})
            decoded = decode_token(token)
            assert "sub" in decoded
            assert "role" in decoded
            assert "exp" in decoded
            assert "iat" in decoded
            assert "jti" in decoded


class TestBootstrapIdempotency:
    """Tests for bootstrap admin creation idempotency."""

    @pytest.mark.asyncio
    async def test_bootstrap_skips_existing_admin(self):
        """Test that bootstrap doesn't create duplicate admins."""
        from app.db.bootstrap import create_bootstrap_admin

        # Mock settings
        with patch("app.db.bootstrap.settings") as mock_settings:
            mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
            mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "secure_password"
            mock_settings.BOOTSTRAP_ADMIN_NAME = "Admin User"

            # Mock the User model to simulate existing user
            with patch("app.db.bootstrap.User") as mock_user:
                mock_existing = MagicMock()
                mock_existing.email = "admin@example.com"
                mock_user.where.return_value.scalar_one_or_none.return_value = mock_existing

                # Mock session
                mock_db = AsyncMock()

                # Call bootstrap
                await create_bootstrap_admin(mock_db)

                # Verify no add/commit happened since user exists
                mock_db.add.assert_not_called()
                mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_bootstrap_creates_admin_when_none_exists(self):
        """Test that bootstrap creates admin when none exists."""
        from app.db.bootstrap import create_bootstrap_admin

        with patch("app.db.bootstrap.settings") as mock_settings:
            mock_settings.BOOTSTRAP_ADMIN_EMAIL = "new_admin@example.com"
            mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "secure_password"
            mock_settings.BOOTSTRAP_ADMIN_NAME = "New Admin"

            with patch("app.db.bootstrap.User") as mock_user:
                mock_user.where.return_value.scalar_one_or_none.return_value = None

                mock_db = AsyncMock()
                mock_db.flush = AsyncMock()

                await create_bootstrap_admin(mock_db)

                # Verify add was called for new entities
                assert mock_db.add.called


class TestBlacklistFunctions:
    """Tests for JWT blacklist functionality."""

    @pytest.mark.asyncio
    async def test_add_to_blacklist(self):
        """Test adding token to blacklist."""
        from app.core.security import add_to_blacklist

        with patch("app.core.security.get_redis_client") as mock_redis:
            mock_redis_client = AsyncMock()
            mock_redis.return_value = mock_redis_client

            with patch("app.core.security.JWTBlacklist"):
                mock_db = AsyncMock()
                await add_to_blacklist("test-jti", mock_db)

                # Verify Redis was called
                mock_redis_client.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_redis_hit(self):
        """Test checking blacklisted token with Redis hit."""
        from app.core.security import is_token_blacklisted

        with patch("app.core.security.get_redis_client") as mock_redis:
            mock_redis_client = AsyncMock()
            mock_redis_client.exists.return_value = 1  # Found in Redis
            mock_redis.return_value = mock_redis_client

            mock_db = AsyncMock()
            result = await is_token_blacklisted("test-jti", mock_db)

            assert result is True
            # DB should not be checked if Redis hit
            mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_db_fallback(self):
        """Test checking blacklisted token with DB fallback."""
        from app.core.security import is_token_blacklisted

        with patch("app.core.security.get_redis_client") as mock_redis:
            mock_redis_client = AsyncMock()
            mock_redis_client.exists.return_value = 0  # Not in Redis
            mock_redis.return_value = mock_redis_client

            with patch("app.core.security.JWTBlacklist") as mock_blacklist:
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None  # Not in DB
                mock_db = AsyncMock()
                mock_db.execute.return_value = mock_result

                result = await is_token_blacklisted("test-jti", mock_db)

                assert result is False