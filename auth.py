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

def _get_clerk_jwks():
    """Fetch Clerk's JWKS (cached for 1 hour)."""
    now = time.time()
    if _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < 3600:
        return _jwks_cache["keys"]
    
    # Clerk exposes JWKS at this endpoint
    # The publishable key encodes the frontend API domain
    pk = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "")
    
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
        jwks_url = f"https://{frontend_api}/.well-known/jwks.json"
    else:
        raise HTTPException(status_code=500, detail="Invalid Clerk publishable key")
    
    try:
        resp = requests.get(jwks_url, timeout=5)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return keys
    except Exception as e:
        print(f"Failed to fetch Clerk JWKS: {e}")
        if _jwks_cache["keys"]:
            return _jwks_cache["keys"]
        raise HTTPException(status_code=500, detail="Could not fetch Clerk JWKS")

async def get_current_user(authorization: str = Header(None)) -> str:
    """
    Verify the Clerk JWT from the Authorization header.
    Returns the Clerk user ID (sub claim).
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # Get Clerk's public keys
        jwks = _get_clerk_jwks()
        
        # Decode the JWT header to get the key ID (kid)
        # PyJWT provides a helper to inspect the header without validating
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        # Find the matching key
        matching_key = None
        for key in jwks:
            if key.get("kid") == kid:
                matching_key = key
                break
        
        if not matching_key:
            raise HTTPException(status_code=401, detail="No matching key found for token")
        
        # Build the public key from JWKS
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(matching_key)
        
        # Verify and decode the token
        payload = jwt.decode(
            token,
            public_key,
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
