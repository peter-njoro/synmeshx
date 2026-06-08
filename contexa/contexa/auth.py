"""
Authentication and identity linking for Contexa.

Handles:
  - Google OAuth 2.0 device flow (no browser required — works in terminal)
  - Local storage of identity tokens in ~/.config/contexa/identity.json
  - Associating the OAuth identity_id (sub claim) with this device in the DB
  - Token expiry detection and re-auth prompting
  - Key-based auth path: devices can authenticate to each other using
    Ed25519 signed challenges instead of OAuth tokens

OAuth flow used: Device Authorization Grant (RFC 8628)
  - User visits a URL and enters a code — no redirect URI needed
  - Works in headless/terminal environments
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import httpx

from contexa.store.models import DeviceRecord


# Google OAuth constants (Device Authorization Grant)

GOOGLE_DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Scope: openid + email gives us the stable `sub` claim as identity_id
OAUTH_SCOPE = "openid email"

# Default config path for identity token storage
DEFAULT_IDENTITY_FILE = Path("~/.config/contexa/identity.json")


# Exceptions

class AuthError(Exception):
    """Raised when authentication fails or is required."""
    pass


class TokenExpiredError(AuthError):
    """Raised when the stored identity token has expired."""
    pass


class NotAuthenticatedError(AuthError):
    """Raised when no identity token is stored."""
    pass


# Data classes

@dataclass
class IdentityToken:
    """Locally stored OAuth identity token."""
    identity_id: str        # OAuth `sub` claim — stable user identifier
    email: str              # User email (for display only)
    access_token: str       # OAuth access token
    refresh_token: str      # OAuth refresh token (for renewal)
    expires_at: float       # Unix timestamp when access_token expires
    provider: str = "google"

    def is_expired(self) -> bool:
        """Return True if the access token has expired (with 60s buffer)."""
        return time.time() >= (self.expires_at - 60)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IdentityToken":
        return cls(**data)


# Token storage

def _token_path(config_dir: Path | None = None) -> Path:
    if config_dir:
        return Path(config_dir).expanduser() / "identity.json"
    return DEFAULT_IDENTITY_FILE.expanduser()


def save_token(token: IdentityToken, config_dir: Path | None = None) -> None:
    """Persist the identity token to local storage."""
    path = _token_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token.to_dict(), indent=2))
    path.chmod(0o600)


def load_token(config_dir: Path | None = None) -> IdentityToken:
    """Load the stored identity token.

    Raises:
        NotAuthenticatedError: If no token file exists.
    """
    path = _token_path(config_dir)
    if not path.exists():
        raise NotAuthenticatedError(
            "Not authenticated. Run: contexa auth login"
        )
    data = json.loads(path.read_text())
    return IdentityToken.from_dict(data)


def clear_token(config_dir: Path | None = None) -> None:
    """Remove the stored identity token (logout)."""
    path = _token_path(config_dir)
    path.unlink(missing_ok=True)


def get_identity_id(config_dir: Path | None = None) -> str:
    """Return the current identity_id, raising if not authenticated or expired.

    Raises:
        NotAuthenticatedError: If no token is stored.
        TokenExpiredError: If the token has expired and cannot be refreshed.
    """
    token = load_token(config_dir)
    if token.is_expired():
        raise TokenExpiredError(
            "Identity token has expired. Run: contexa auth login"
        )
    return token.identity_id


# Google OAuth Device Flow

def start_device_flow(client_id: str) -> dict:
    """Start the Google OAuth device authorization flow.

    Returns the device_code response containing:
      - device_code, user_code, verification_url, expires_in, interval
    """
    r = httpx.post(
        GOOGLE_DEVICE_AUTH_URL,
        data={"client_id": client_id, "scope": OAUTH_SCOPE},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()


def poll_for_token(client_id: str, client_secret: str, device_code: str, interval: int) -> dict:
    """Poll Google's token endpoint until the user completes authorization.

    Returns the token response dict on success.
    Raises AuthError on failure or timeout.
    """
    max_attempts = 60  # 5 minutes at 5s interval
    for _ in range(max_attempts):
        time.sleep(interval)
        r = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=10.0,
        )
        data = r.json()
        if "access_token" in data:
            return data
        error = data.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise AuthError(f"OAuth error: {error} — {data.get('error_description', '')}")

    raise AuthError("Authentication timed out. Please try again.")


def fetch_userinfo(access_token: str) -> dict:
    """Fetch the user's profile from Google to get the stable `sub` claim."""
    r = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()


def login(
    client_id: str,
    client_secret: str,
    config_dir: Path | None = None,
) -> IdentityToken:
    """Run the full Google OAuth device flow and store the resulting token.

    Prints instructions to stdout for the user to complete in a browser.

    Returns:
        The stored IdentityToken.
    """
    # Step 1: Get device code
    flow = start_device_flow(client_id)
    print(f"\nOpen this URL in your browser:\n  {flow['verification_url']}")
    print(f"\nEnter this code: {flow['user_code']}\n")

    # Step 2: Poll for token
    token_data = poll_for_token(
        client_id,
        client_secret,
        flow["device_code"],
        interval=flow.get("interval", 5),
    )

    # Step 3: Get user identity
    userinfo = fetch_userinfo(token_data["access_token"])

    token = IdentityToken(
        identity_id=userinfo["sub"],
        email=userinfo.get("email", ""),
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", ""),
        expires_at=time.time() + token_data.get("expires_in", 3600),
    )
    save_token(token, config_dir)
    return token


def refresh_token(config_dir: Path | None = None, client_id: str = "", client_secret: str = "") -> IdentityToken:
    """Attempt to refresh an expired token using the stored refresh_token.

    Raises:
        NotAuthenticatedError: If no token is stored or refresh fails.
    """
    token = load_token(config_dir)
    if not token.refresh_token:
        raise NotAuthenticatedError("No refresh token available. Run: contexa auth login")

    r = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10.0,
    )
    data = r.json()
    if "access_token" not in data:
        raise NotAuthenticatedError(
            f"Token refresh failed: {data.get('error', 'unknown')}. Run: contexa auth login"
        )

    token.access_token = data["access_token"]
    token.expires_at = time.time() + data.get("expires_in", 3600)
    save_token(token, config_dir)
    return token


# Device-to-device identity verification

def verify_device_identity(
    device_id: str,
    claimed_identity_id: str,
    session,
) -> bool:
    """Verify that a device's claimed identity_id matches what's stored in the DB.

    Used by the Sync_Engine to ensure both devices belong to the same user
    before exchanging any context data.

    Args:
        device_id: The Device_ID of the peer.
        claimed_identity_id: The identity_id the peer claims to have.
        session: SQLAlchemy session.

    Returns:
        True if the device's stored identity_id matches the claimed one.
    """
    device = session.get(DeviceRecord, device_id)
    if device is None:
        return False
    if device.identity_id is None:
        return False
    return device.identity_id == claimed_identity_id


def associate_identity(
    device_id: str,
    identity_id: str,
    session,
) -> None:
    """Associate an identity_id with a device in the database.

    Called after successful OAuth login to link this device to the user.

    Args:
        device_id: This device's UUID.
        identity_id: The OAuth `sub` claim.
        session: SQLAlchemy session.
    """
    device = session.get(DeviceRecord, device_id)
    if device is None:
        raise AuthError(f"Device '{device_id}' not found. Run: contexa daemon start")
    device.identity_id = identity_id
    session.commit()
