
from functools import lru_cache
from pydantic_settings import BaseSettings
import jwt 
from fastapi.security import SecurityScopes, HTTPAuthorizationCredentials,  HTTPBearer
from fastapi import  Depends ,WebSocket, WebSocketException, status, HTTPException, Request
from db.definition import create_update_user
from typing import Optional
import os
from secrets import compare_digest
from contextvars import ContextVar
from dotenv import load_dotenv
load_dotenv()
 


REQUEST_CTX_KEY = "request_context"
_request_ctx_var: ContextVar[str] = ContextVar(REQUEST_CTX_KEY, default=None)

class Settings(BaseSettings):
    auth0_domain: str
    auth0_api_audience: str
    auth0_issuer: str 
    auth0_algorithms: str

    class Config:
        env_file = ".env"
        extra = "allow" 

@lru_cache()
def get_settings():
    return Settings()

class UnauthorizedException(HTTPException):
    def __init__(self, detail: str, **kwargs):
        """Returns HTTP 403"""
        super().__init__(status.HTTP_403_FORBIDDEN, detail=detail)

class UnauthenticatedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Requires authentication"
        )


def _validate_client_secret(request: Request, environment_name: str):
    expected = os.getenv(environment_name)
    supplied = request.headers.get("X-API-Key")
    if (
        not expected
        or not expected.strip()
        or not supplied
        or not supplied.strip()
        or not compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return True


def ui_client_validation(request: Request):
    return _validate_client_secret(request, "UI_CLIENT_SECRET")

def mcp_client_validation(request: Request):
    return _validate_client_secret(request, "MCP_SECRET_API_KEY")

class VerifyToken:
    """Does all the token verification using PyJWT"""

    def __init__(self):
            self.config = get_settings()

            # This gets the JWKS from a given URL and does processing so you can
            # use any of the keys available
            jwks_url = f'https://{self.config.auth0_domain}/.well-known/jwks.json'
            self.jwks_client = jwt.PyJWKClient(jwks_url)

    async def verify(self,
                        security_scopes: SecurityScopes,
                        token: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer())
                        ):
            if token.credentials == "unauthenticated": return None 

            # This gets the 'kid' from the passed token
            try:
                signing_key = self.jwks_client.get_signing_key_from_jwt(
                    token.credentials
                ).key
            except jwt.exceptions.PyJWKClientError as error:
                raise UnauthorizedException(str(error))
            except jwt.exceptions.DecodeError as error:
                raise UnauthorizedException(str(error))

            try:
                payload = jwt.decode(
                    token.credentials,
                    signing_key,
                    algorithms=self.config.auth0_algorithms,
                    audience=self.config.auth0_api_audience,
                    issuer=self.config.auth0_issuer,
                )
            except Exception as error:
                raise UnauthorizedException(str(error))
        
            #create or update user in db
            create_update_user(payload['sub'])
            return payload
