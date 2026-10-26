"""Sign in with Apple: the client secret is a short-lived ES256 JWT signed with the team's .p8 key."""
import base64
import json
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

AUTH_URL = "https://appleid.apple.com/auth/authorize"
TOKEN_URL = "https://appleid.apple.com/auth/token"
ISSUER = "https://appleid.apple.com"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def client_secret(settings: dict) -> str:
    header = {"alg": "ES256", "kid": settings["apple_key_id"]}
    now = int(time.time())
    claims = {"iss": settings["apple_team_id"], "iat": now, "exp": now + 300, "aud": ISSUER, "sub": settings["apple_client_id"]}
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}".encode()
    key = serialization.load_pem_private_key(settings["apple_private_key"].strip().encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("The Apple key must be the .p8 (EC) key from your Apple developer account.")
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    return f"{signing_input.decode()}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
