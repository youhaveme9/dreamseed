from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, ed448, rsa
from mcp.server.auth.provider import AccessToken


REQUIRED_SCOPE = "dreamseed:use"


@dataclass(frozen=True)
class HttpAuthConfig:
    issuer: str
    resource: str
    subject: str
    public_key: str
    algorithm: str = "EdDSA"

    def __post_init__(self):
        for value in (self.issuer, self.resource):
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("issuer and resource must be explicit HTTPS URLs without credentials, query, or fragment")
        if not self.resource.endswith("/mcp"):
            raise ValueError("resource URL must end in /mcp")
        if not self.subject or len(self.subject) > 256:
            raise ValueError("one authorized owner subject is required")
        if self.algorithm not in {"EdDSA", "RS256", "ES256"}:
            raise ValueError("only EdDSA, RS256, and ES256 public key verification is supported")
        key = serialization.load_pem_public_key(self.public_key.encode())
        if self.algorithm == "RS256" and (not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048):
            raise ValueError("RS256 requires an RSA public key of at least 2048 bits")
        if self.algorithm == "ES256" and (not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1)):
            raise ValueError("ES256 requires a P256 public key")
        if self.algorithm == "EdDSA" and not isinstance(key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            raise ValueError("EdDSA requires an Ed25519 or Ed448 public key")
        jwt.get_algorithm_by_name(self.algorithm).prepare_key(self.public_key)

    @classmethod
    def from_environment(cls) -> HttpAuthConfig:
        names = ("DREAMSEED_HTTP_ISSUER", "DREAMSEED_HTTP_RESOURCE", "DREAMSEED_HTTP_SUBJECT", "DREAMSEED_HTTP_PUBLIC_KEY")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError("missing HTTP authentication settings: " + ", ".join(missing))
        return cls(*(os.environ[name] for name in names), algorithm=os.environ.get("DREAMSEED_HTTP_ALGORITHM", "EdDSA"))


class JwtTokenVerifier:
    def __init__(self, config: HttpAuthConfig):
        self.config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        if len(token) > 16384:
            return None
        try:
            claims = jwt.decode(
                token, self.config.public_key, algorithms=[self.config.algorithm],
                audience=self.config.resource, issuer=self.config.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject, scope = claims.get("sub"), claims.get("scope")
            client_id = claims.get("client_id", claims.get("azp"))
            if subject != self.config.subject or not isinstance(scope, str) or len(scope) > 4096:
                return None
            scopes = scope.split()
            if REQUIRED_SCOPE not in scopes or not isinstance(client_id, str) or not 1 <= len(client_id) <= 256:
                return None
            if type(claims["exp"]) is not int or type(claims["iat"]) is not int:
                return None
            return AccessToken(
                token=token, client_id=client_id, subject=subject, scopes=scopes,
                expires_at=claims["exp"], resource=self.config.resource,
                claims={"iss": self.config.issuer, "sub": subject},
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            return None
