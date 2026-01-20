"""Tech stack detection from project files.

Detects core languages from common project files like
package.json, pyproject.toml, Cargo.toml, go.mod, etc.
"""

import json
from pathlib import Path


def detect_stack(project_path: Path) -> list[str]:
    """Detect tech stack from project files.

    Args:
        project_path: Path to project root directory

    Returns:
        List of detected framework/language identifiers
    """
    stack = set()

    # Python
    pyproject = project_path / "pyproject.toml"
    requirements = project_path / "requirements.txt"

    if pyproject.exists() or requirements.exists():
        stack.add("python")

    # JavaScript/TypeScript
    package_json = project_path / "package.json"
    manifest_json = project_path / "manifest.json"

    if package_json.exists():
        deps = _parse_package_json(package_json)
        # Detect if TypeScript
        if "typescript" in deps or (project_path / "tsconfig.json").exists():
            stack.add("typescript")
        else:
            stack.add("javascript")
    elif manifest_json.exists():
        # Browser extension (Chrome/Firefox)
        if _is_browser_extension(manifest_json):
            stack.add("javascript")

    # Rust
    cargo_toml = project_path / "Cargo.toml"
    if cargo_toml.exists():
        stack.add("rust")

    # Go
    go_mod = project_path / "go.mod"
    if go_mod.exists():
        stack.add("go")

    return sorted(stack)


def _parse_package_json(path: Path) -> set[str]:
    """Extract dependencies from package.json."""
    deps = set()
    try:
        data = json.loads(path.read_text())
        for key in ["dependencies", "devDependencies", "peerDependencies"]:
            if key in data and isinstance(data[key], dict):
                deps.update(data[key].keys())
    except Exception:
        pass

    return deps


def _is_browser_extension(path: Path) -> bool:
    """Check if manifest.json is a browser extension manifest."""
    try:
        data = json.loads(path.read_text())
        # Browser extensions have manifest_version and typically background/content_scripts
        if "manifest_version" in data:
            # Check for extension-specific keys
            extension_keys = ["background", "content_scripts", "browser_action", "action", "permissions"]
            return any(key in data for key in extension_keys)
    except Exception:
        pass
    return False


