"""Tech stack detection from project files.

Detects frameworks and languages from common project files like
package.json, pyproject.toml, Cargo.toml, go.mod, etc.
"""

import json
import re
from pathlib import Path

# Framework detection mappings
# Keys are package/dependency names, values are the canonical framework name

PYTHON_FRAMEWORKS = {
    # Web frameworks
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "starlette": "starlette",
    "tornado": "tornado",
    "aiohttp": "aiohttp",
    # AI/ML
    "anthropic": "anthropic-sdk",
    "openai": "openai-sdk",
    "langchain": "langchain",
    "transformers": "huggingface",
    "torch": "pytorch",
    "tensorflow": "tensorflow",
    # Testing
    "pytest": "pytest",
    # Data
    "pandas": "pandas",
    "numpy": "numpy",
    "sqlalchemy": "sqlalchemy",
}

JS_FRAMEWORKS = {
    # Frontend
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "angular": "angular",
    "next": "nextjs",
    "nuxt": "nuxt",
    "gatsby": "gatsby",
    # Backend
    "express": "express",
    "fastify": "fastify",
    "koa": "koa",
    "hono": "hono",
    # Runtime/build
    "typescript": "typescript",
    "vite": "vite",
    "esbuild": "esbuild",
    # Testing
    "jest": "jest",
    "vitest": "vitest",
    "playwright": "playwright",
}

RUST_FRAMEWORKS = {
    "axum": "axum",
    "actix-web": "actix",
    "rocket": "rocket",
    "tokio": "tokio",
    "serde": "serde",
    "clap": "clap",
}

GO_FRAMEWORKS = {
    "gin": "gin",
    "echo": "echo",
    "fiber": "fiber",
    "chi": "chi",
    "gorilla/mux": "gorilla",
}


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

    if pyproject.exists():
        stack.add("python")
        deps = _parse_pyproject(pyproject)
        stack.update(_detect_frameworks(deps, PYTHON_FRAMEWORKS))
    elif requirements.exists():
        stack.add("python")
        deps = _parse_requirements(requirements)
        stack.update(_detect_frameworks(deps, PYTHON_FRAMEWORKS))

    # JavaScript/TypeScript
    package_json = project_path / "package.json"
    if package_json.exists():
        deps = _parse_package_json(package_json)
        # Detect if TypeScript
        if "typescript" in deps or (project_path / "tsconfig.json").exists():
            stack.add("typescript")
        else:
            stack.add("javascript")
        stack.update(_detect_frameworks(deps, JS_FRAMEWORKS))

    # Rust
    cargo_toml = project_path / "Cargo.toml"
    if cargo_toml.exists():
        stack.add("rust")
        deps = _parse_cargo_toml(cargo_toml)
        stack.update(_detect_frameworks(deps, RUST_FRAMEWORKS))

    # Go
    go_mod = project_path / "go.mod"
    if go_mod.exists():
        stack.add("go")
        deps = _parse_go_mod(go_mod)
        stack.update(_detect_frameworks(deps, GO_FRAMEWORKS))

    return sorted(stack)


def _detect_frameworks(deps: set[str], framework_map: dict[str, str]) -> set[str]:
    """Match dependencies against framework mappings."""
    detected = set()
    for dep in deps:
        dep_lower = dep.lower()
        for pattern, framework in framework_map.items():
            if pattern in dep_lower:
                detected.add(framework)
    return detected


def _parse_pyproject(path: Path) -> set[str]:
    """Extract dependencies from pyproject.toml."""
    deps = set()
    try:
        content = path.read_text()

        # Simple regex parsing (avoids toml dependency)
        # Match dependencies = [...] or [project.dependencies]
        dep_pattern = r'dependencies\s*=\s*\[(.*?)\]'
        matches = re.findall(dep_pattern, content, re.DOTALL)

        for match in matches:
            # Extract package names from quoted strings
            packages = re.findall(r'["\']([a-zA-Z0-9_-]+)', match)
            deps.update(packages)

        # Also check [tool.poetry.dependencies] style
        poetry_pattern = r'\[tool\.poetry\.dependencies\](.*?)(?:\[|$)'
        poetry_matches = re.findall(poetry_pattern, content, re.DOTALL)

        for match in poetry_matches:
            # Match package = "version" or package = {version = "..."}
            packages = re.findall(r'^([a-zA-Z0-9_-]+)\s*=', match, re.MULTILINE)
            deps.update(packages)

    except Exception:
        pass

    return deps


def _parse_requirements(path: Path) -> set[str]:
    """Extract dependencies from requirements.txt."""
    deps = set()
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                # Extract package name (before ==, >=, etc.)
                match = re.match(r'^([a-zA-Z0-9_-]+)', line)
                if match:
                    deps.add(match.group(1))
    except Exception:
        pass

    return deps


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


def _parse_cargo_toml(path: Path) -> set[str]:
    """Extract dependencies from Cargo.toml."""
    deps = set()
    try:
        content = path.read_text()

        # Match [dependencies] section
        dep_section = re.search(r'\[dependencies\](.*?)(?:\[|$)', content, re.DOTALL)
        if dep_section:
            # Match package = "version" or package = {...}
            packages = re.findall(r'^([a-zA-Z0-9_-]+)\s*=', dep_section.group(1), re.MULTILINE)
            deps.update(packages)

    except Exception:
        pass

    return deps


def _parse_go_mod(path: Path) -> set[str]:
    """Extract dependencies from go.mod."""
    deps = set()
    try:
        content = path.read_text()

        # Match require ( ... ) block
        require_block = re.search(r'require\s*\((.*?)\)', content, re.DOTALL)
        if require_block:
            # Extract module paths
            modules = re.findall(r'^\s*([^\s]+)', require_block.group(1), re.MULTILINE)
            for module in modules:
                # Extract last part of path (e.g., github.com/gin-gonic/gin -> gin)
                parts = module.split("/")
                if parts:
                    deps.add(parts[-1])

        # Also match single-line requires
        single_requires = re.findall(r'require\s+([^\s]+)', content)
        for module in single_requires:
            parts = module.split("/")
            if parts:
                deps.add(parts[-1])

    except Exception:
        pass

    return deps
