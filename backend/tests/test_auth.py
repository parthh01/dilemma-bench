"""Client authentication checks without local secrets, database access, or JWKS."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import secrets
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, SecurityScopes


BACKEND = Path(__file__).resolve().parents[1]


def load_auth():
    database = types.ModuleType("db.definition")
    database.create_update_user = Mock()
    spec = importlib.util.spec_from_file_location("offline_auth", BACKEND / "auth.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"db.definition": database}), patch("dotenv.load_dotenv"):
        spec.loader.exec_module(module)
    return module


def request_with_key(value):
    headers = [] if value is None else [(b"x-api-key", value.encode("latin-1"))]
    return Request({"type": "http", "headers": headers})


class ClientSecretTests(unittest.TestCase):
    def setUp(self):
        self.auth = load_auth()

    def validators(self):
        return (
            (self.auth.ui_client_validation, "UI_CLIENT_SECRET"),
            (self.auth.mcp_client_validation, "MCP_SECRET_API_KEY"),
        )

    def test_missing_empty_and_whitespace_secrets_fail_closed(self):
        for validate, setting in self.validators():
            for expected in (None, "", "   "):
                for supplied in (None, "", "   ", "synthetic-key"):
                    with self.subTest(setting=setting, expected=expected, supplied=supplied):
                        environment = types.SimpleNamespace(getenv=Mock(return_value=expected))
                        with patch.object(self.auth, "os", environment):
                            with self.assertRaises(HTTPException) as raised:
                                validate(request_with_key(supplied))
                        self.assertEqual(raised.exception.status_code, 403)
                        self.assertEqual(raised.exception.detail, "Not authorized")
                        environment.getenv.assert_called_once_with(setting)

    def test_configured_secret_rejects_absent_wrong_and_non_ascii_headers(self):
        for validate, setting in self.validators():
            for supplied in (None, "", "   ", "different-key", "differént-key"):
                with self.subTest(setting=setting, supplied=supplied):
                    environment = types.SimpleNamespace(getenv=Mock(return_value="synthetic-key"))
                    with patch.object(self.auth, "os", environment):
                        with self.assertRaises(HTTPException) as raised:
                            validate(request_with_key(supplied))
                    self.assertEqual(raised.exception.status_code, 403)

    def test_matching_secret_uses_constant_time_comparison(self):
        for validate, setting in self.validators():
            with self.subTest(setting=setting):
                environment = types.SimpleNamespace(getenv=Mock(return_value="synthetic-key"))
                with patch.object(self.auth, "os", environment), patch.object(
                    self.auth, "compare_digest", wraps=secrets.compare_digest
                ) as compare:
                    self.assertTrue(validate(request_with_key("synthetic-key")))
                compare.assert_called_once_with(b"synthetic-key", b"synthetic-key")
                environment.getenv.assert_called_once_with(setting)


class TokenPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.auth = load_auth()
        # Inject dependencies without invoking Settings or constructing JWKS.
        self.verifier = self.auth.VerifyToken.__new__(self.auth.VerifyToken)
        self.verifier.config = types.SimpleNamespace(
            auth0_algorithms="RS256", auth0_api_audience="offline-audience",
            auth0_issuer="https://offline.invalid/",
        )
        self.verifier.jwks_client = Mock()
        self.verifier.jwks_client.get_signing_key_from_jwt.return_value.key = "synthetic-signing-key"

    def test_successful_verification_does_not_log_personal_claims(self):
        payload = {"sub": "synthetic-user", "email": "test@example.invalid", "name": "Private Test Name"}
        stdout, stderr = io.StringIO(), io.StringIO()
        token = HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic-token")
        with patch.object(self.auth.jwt, "decode", return_value=payload), redirect_stdout(stdout), redirect_stderr(stderr):
            result = asyncio.run(self.verifier.verify(SecurityScopes(), token))
        self.assertEqual(result, payload)
        self.auth.create_update_user.assert_called_once_with("synthetic-user")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_intentional_guest_token_behavior_is_unchanged(self):
        token = HTTPAuthorizationCredentials(scheme="Bearer", credentials="unauthenticated")
        result = asyncio.run(self.verifier.verify(SecurityScopes(), token))
        self.assertIsNone(result)
        self.verifier.jwks_client.get_signing_key_from_jwt.assert_not_called()
        self.auth.create_update_user.assert_not_called()


class DatabaseLoggingTests(unittest.TestCase):
    def test_both_database_engines_disable_sql_parameter_echo(self):
        spec = importlib.util.spec_from_file_location("offline_database_definition", BACKEND / "db" / "definition.py")
        module = importlib.util.module_from_spec(spec)
        configuration = {
            "POSTGRES_USER": "offline", "POSTGRES_PASSWORD": "synthetic-password",
            "POSTGRES_HOST": "offline.invalid", "POSTGRES_PORT": "5432", "POSTGRES_DB": "offline",
        }
        with patch.dict("os.environ", configuration, clear=True), patch("sqlalchemy.create_engine") as sync_engine, patch(
            "sqlalchemy.ext.asyncio.create_async_engine"
        ) as async_engine:
            spec.loader.exec_module(module)
        sync_engine.assert_called_once()
        async_engine.assert_called_once()
        self.assertIs(sync_engine.call_args.kwargs["echo"], False)
        self.assertIs(async_engine.call_args.kwargs["echo"], False)


if __name__ == "__main__":
    unittest.main()
