"""Simple licensing for Pro features."""

import os
from pathlib import Path


class LicenseError(Exception):
    """Raised when a Pro feature is used without valid license."""

    pass


# Features that require a Pro license
PRO_FEATURES = {
    "rules": "Automatic rule extraction from session summaries",
    "vault": "Publish and install community rule sets",
}


def check_license(feature: str) -> bool:
    """Check if user has valid license for a Pro feature.

    License key format: AP-PRO-{identifier}
    Stored in .env as AFTERPATHS_LICENSE_KEY

    Args:
        feature: The feature to check (e.g., "distill")

    Returns:
        True if licensed

    Raises:
        LicenseError: If no valid license found
    """
    license_key = os.environ.get("AFTERPATHS_LICENSE_KEY", "")

    if not license_key:
        raise LicenseError(
            f"'{feature}' is a Pro feature.\n"
            f"Get a license at https://afterpaths.dev/pro\n"
            f"Then run: afterpaths activate <license-key>"
        )

    if not validate_license_key(license_key, feature):
        raise LicenseError(
            f"License key not valid for '{feature}'.\n"
            f"Your key: {license_key[:10]}...\n"
            f"Get an upgraded license at https://afterpaths.dev/pro"
        )

    return True


def validate_license_key(key: str, feature: str) -> bool:
    """Validate license key format and feature access.

    For MVP, uses simple prefix validation.
    Production would use cryptographic signature verification.

    Args:
        key: The license key to validate
        feature: The feature being accessed

    Returns:
        True if the key is valid for the feature
    """
    # Accept any key starting with AP-PRO- (full access)
    # or AP-{FEATURE}- (feature-specific access)
    valid_prefixes = [
        "AP-PRO-",
        f"AP-{feature.upper()}-",
    ]

    return any(key.startswith(prefix) for prefix in valid_prefixes)


def activate_license(key: str) -> bool:
    """Store license key in .env file.

    Args:
        key: The license key to store

    Returns:
        True if successfully stored
    """
    env_path = Path.cwd() / ".env"

    # Read existing .env
    existing = ""
    if env_path.exists():
        existing = env_path.read_text()

    # Remove existing license key line if present
    lines = existing.split("\n")
    lines = [l for l in lines if not l.startswith("AFTERPATHS_LICENSE_KEY=")]
    existing = "\n".join(lines)

    # Add new license key
    new_content = existing.rstrip()
    if new_content:
        new_content += "\n"
    new_content += f"AFTERPATHS_LICENSE_KEY={key}\n"

    env_path.write_text(new_content)
    return True


def get_license_status() -> dict:
    """Get current license status.

    Returns:
        Dict with license info and enabled features
    """
    key = os.environ.get("AFTERPATHS_LICENSE_KEY", "")

    if not key:
        return {
            "licensed": False,
            "key": None,
            "features": [],
        }

    # Check which features are enabled
    enabled = []
    for feature in PRO_FEATURES:
        if validate_license_key(key, feature):
            enabled.append(feature)

    return {
        "licensed": bool(enabled),
        "key": key[:10] + "..." if len(key) > 10 else key,
        "features": enabled,
    }
