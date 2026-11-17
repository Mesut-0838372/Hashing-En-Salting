"""Scan Python imports and optionally update project dependencies.

Requires Python 3.11+. No third-party packages are needed for scanning.
Usage: python dependency_auto.py [PROJECT_DIR] [--apply]
"""

import argparse
import ast
import importlib.metadata as metadata
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SKIP_DIRS = {".venv", "venv", "env", ".git", ".idea", "__pycache__", "build", "dist", "node_modules"}
PACKAGE_HINTS = {"argon2": "argon2-cffi", "PIL": "Pillow", "yaml": "PyYAML", "cv2": "opencv-python",
                 "sklearn": "scikit-learn", "bs4": "beautifulsoup4", "dotenv": "python-dotenv"}
README_START = "<!-- AUTO-GENERATED:START -->"
README_END = "<!-- AUTO-GENERATED:END -->"


def scan(root: Path):
    imported = set()
    local = set()
    for file in root.rglob("*.py"):
        if set(file.relative_to(root).parts) & SKIP_DIRS:
            continue
        if file.parent == root:
            local.add(file.stem)
        for parent in file.parents:
            if parent == root or root not in parent.parents:
                break
            if (parent / "__init__.py").exists():
                local.add(parent.name)
        try:
            tree = ast.parse(file.read_text(encoding="utf-8-sig"), filename=str(file))
        except (SyntaxError, UnicodeError) as exc:
            print(f"WARNING: Cannot scan {file}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    standard = sys.stdlib_module_names | set(sys.builtin_module_names)
    return sorted(imported - local - standard)


def normalize(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def resolve(imports):
    mapping = metadata.packages_distributions()
    known, unresolved = {}, []
    for name in imports:
        distributions = mapping.get(name, [])
        hint = PACKAGE_HINTS.get(name)
        if hint and (not distributions or hint in distributions):
            distributions = [hint]
        if len(distributions) == 1:
            distribution = distributions[0]
            try:
                version = metadata.version(distribution)
            except metadata.PackageNotFoundError:
                unresolved.append(name)
                continue
            known[normalize(distribution)] = (distribution, version, name)
        else:
            unresolved.append(name)
    return known, unresolved


def update_toml(path, found):
    if path.exists():
        content = path.read_text(encoding="utf-8")
        data = tomllib.loads(content)
    else:
        content = '[project]\nname = "' + re.sub(r"[^a-z0-9-]+", "-",
                                                 path.parent.name.lower()) + '"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        data = tomllib.loads(content)
    if "project" not in data or not isinstance(data["project"], dict):
        raise ValueError("Expected a [project] section. No modifications made.")
    current = data["project"].get("dependencies", [])
    if not isinstance(current, list) or not all(isinstance(d, str) for d in current):
        raise ValueError("Unsupported dependencies format. No modifications made.")
    existing = {normalize(re.split(r"[<>=!~;\[ ]", d, maxsplit=1)[0]) for d in current}
    additions = [f"{dist}>={version}" for key, (dist, version, _) in sorted(found.items()) if key not in existing]
    if not additions:
        return []
    if "dependencies" in data["project"]:
        # Let uv safely modify existing TOML structure.
        subprocess.run(["uv", "add", "--no-sync", *additions], cwd=path.parent, check=True)
        return additions
    section = re.search(r"(?m)^\[project\]\s*$", content)
    assert section is not None
    next_section = re.search(r"(?m)^\[", content[section.end():])
    end = section.end() + next_section.start() if next_section else len(content)
    block = '\n' + 'dependencies = [\n' + ''.join(f'    "{entry}",\n' for entry in additions) + ']\n'
    updated = content[:end].rstrip() + '\n' + block + '\n' + content[end:].lstrip('\n')
    tomllib.loads(updated)
    path.write_text(updated, encoding="utf-8")
    return additions


def readme_content(root: Path) -> str:
    """Build a technical overview from project configuration, not guesses about code."""
    project_file = root / "pyproject.toml"
    project = {}
    if project_file.exists():
        project = tomllib.loads(project_file.read_text(encoding="utf-8")).get("project", {})
    name = project.get("name", root.name)
    python_version = project.get("requires-python", "not specified")
    packages = project.get("dependencies", [])
    lines = ["## Project configuration", "", f"- **Project:** {name}", f"- **Python requirement:** `{python_version}`",
             "", "## Direct dependencies", ""]
    lines += [f"- `{dep}`" for dep in packages] if packages else ["No direct dependencies declared."]
    lines += ["", "## Installation", "", "```powershell", "python -m venv .venv", ".venv\\Scripts\\Activate.ps1",
              "python -m pip install -r requirements.txt", "```", "", "## Tests", ""]
    test_files = [p for p in root.rglob("test_*.py") if not (set(p.relative_to(root).parts) & SKIP_DIRS)]
    test_files += [p for p in root.rglob("*_test.py") if
                   not (set(p.relative_to(root).parts) & SKIP_DIRS) and p not in test_files]
    if (root / "pytest.ini").exists() or any("pytest" in d.lower() for d in packages):
        lines += [f"Detected {len(test_files)} test file(s).", "", "```powershell", "python -m pytest", "```"]
    elif test_files:
        lines += [f"Detected {len(test_files)} possible test file(s). Verify the test runner before running them."]
    else:
        lines += ["No automated test files detected."]
    return "\n".join(lines) + "\n"


def update_readme(root: Path) -> None:
    path = root / "README.md"
    if path.exists():
        old = path.read_text(encoding="utf-8")
    else:
        old = f"# {root.name}\n\n## Description\n\nDescribe your project here.\n\n"
    start_count, end_count = old.count(README_START), old.count(README_END)
    if (start_count, end_count) not in {(0, 0), (1, 1)}:
        print("README markers are inconsistent; README.md was not changed.")
        return
    section = README_START + "\n" + readme_content(root) + README_END
    if start_count == 1:
        before, tail = old.split(README_START, 1)
        _, after = tail.split(README_END, 1)
        updated = before + section + after
    else:
        updated = old.rstrip() + "\n\n" + section + "\n"
    if updated != old:
        path.write_text(updated, encoding="utf-8")
        print("README.md: automatically managed section updated; manual text preserved.")
    else:
        print("README.md: already up to date.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="Update dependencies and README (requires uv)")
    args = parser.parse_args()
    root = args.project.resolve()
    if not root.is_dir():
        parser.error("Project directory does not exist")
    imports = scan(root)
    found, unresolved = resolve(imports)
    print("Detected installed distributions:")
    for dist, version, imported in sorted(found.values()):
        print(f"  {imported} -> {dist}=={version}")
    if unresolved:
        print("UNRESOLVED (review manually): " + ", ".join(unresolved))
    if not args.apply:
        print("Preview only. Run with --apply to update the project.")
        return
    if unresolved:
        print("Stopped: cannot safely automate ambiguous or missing imports.")
        sys.exit(2)
    if not found:
        print("No external imports found; existing project dependencies will be preserved.")
        update_readme(root)
        return
    path = root / "pyproject.toml"
    try:
        additions = update_toml(path, found)
    except FileNotFoundError:
        print("uv not installed. Install with: python -m pip install uv")
        sys.exit(1)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Stopped without compiling: {exc}")
        sys.exit(1)
    if not path.exists():
        print("No pyproject.toml created.")
        return
    if additions:
        print("Added to pyproject.toml: " + ", ".join(additions))
    print("Generating requirements.txt with uv, if available...")
    try:
        subprocess.run(["uv", "pip", "compile", "pyproject.toml", "--output-file", "requirements.txt"], cwd=root,
                       check=True)
    except FileNotFoundError:
        print("uv not installed. Install with: python -m pip install uv")
    except subprocess.CalledProcessError:
        print("Compile failed; check pyproject.toml. No requirements.txt changes were guaranteed.")
        sys.exit(1)
    update_readme(root)


if __name__ == "__main__":
    main()
