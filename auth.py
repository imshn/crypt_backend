from fastapi import Header, HTTPException
# The PyJWT library installs to the "jwt" module namespace.
# We still import it as jwt to match the package name.
import jwt
import requests
import os
import time
from typing import Optional

# Cache JWKS to avoid fetching on every request
_jwks_cache = {"keys": None, "fetched_at": 0}

def _get_clerk_jwks_url() -> str:
    """Return the JWKS URL for the current Clerk project.

    We don't actually download the keys here; PyJWT's PyJWKClient will
    handle fetching and caching internally.  This helper only derives the
    URL from the publishable key, crashing if the key is missing or malformed.
    """
    pk = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "")
    if not pk:
        # crash early with explanatory message (will show in Vercel logs)
        raise HTTPException(status_code=500, detail="Clerk publishable key not set on backend")

    # Extract the frontend API URL from the publishable key
    # pk_test_<base64-encoded-frontend-api>
    if pk.startswith("pk_test_") or pk.startswith("pk_live_"):
        import base64
        encoded = pk.split("_", 2)[2]
        # Add padding if needed
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += "=" * padding
        frontend_api = base64.b64decode(encoded).decode("utf-8").rstrip("$")
        return f"https://{frontend_api}/.well-known/jwks.json"

    raise HTTPException(status_code=500, detail="Invalid Clerk publishable key")

async def get_current_user(authorization: str = Header(None)) -> str:
    """
    Verify the Clerk JWT from the Authorization header.
    Returns the Clerk user ID (sub claim).
    """
    # logging token presence helps troubleshoot production issues
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # derive the JWKS URL and let PyJWT handle the rest
        jwks_url = _get_clerk_jwks_url()
        print("using JWKS URL", jwks_url)

        from jwt import PyJWKClient
        jwk_client = PyJWKClient(jwks_url)

        # this call fetches (and caches) the appropriate key for the token
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        print("signing_key", signing_key)

        # Verify and decode the token in one step
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False}  # Clerk doesn't set audience by default
        )
        
        # Return the Clerk user ID
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing user ID")
        
        return user_id
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")
