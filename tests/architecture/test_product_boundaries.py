"""Gate 1B - executable product-boundary guards (ADR-001 / ADR-002 / ADR-003).

LIMITATIONS - READ BEFORE TRUSTING THESE TESTS.

These tests enforce DIRECT STATIC IMPORTS ONLY. They parse `agent_core/**/*.py` with `ast` and
never import production modules. They therefore do NOT fully detect:

  - importlib.import_module
  - __import__
  - string-based plugin loading
  - dependency-injection misconfiguration
  - service locators
  - runtime plugin registration
  - adapter side effects

They are NOT a proof of complete runtime dependency safety or authority isolation. Runtime
composition and adapter wiring must be covered by integration tests in later gates.

Most boundaries below are RESERVED: the package does not exist yet, so the rule is currently
vacuous - it constrains future code rather than certifying current code. Only the ChangeGate
boundary (`agent_core.build_harness`) is actively exercised today, and
`test_current_changegate_boundary_is_non_vacuous` proves that.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_CORE = REPO_ROOT / "agent_core"

# --- product boundary prefixes ---------------------------------------------
# `agent_core.build_harness` is the CURRENT ChangeGate-oriented implementation boundary
# (ADR-001 s5). It is not renamed or reclassified to make any test pass.
KERNEL_PREFIXES = ("agent_core.kernel",)
CHANGEGATE_PREFIXES = ("agent_core.changegate", "agent_core.build_harness")
PROJECT_CONTROL_PREFIXES = ("agent_core.project_control",)
COORDINATOR_PREFIXES = ("agent_core.coordinator",)
SOFTWARE_DELIVERY_COMPOSITION_PREFIXES = (
    "agent_core.workflows.software_delivery",
    "agent_core.software_delivery_workflow",
)
ADAPTER_PREFIXES = ("agent_core.adapters",)

BOUNDARY_GROUPS: dict[str, tuple[str, ...]] = {
    "Kernel/Core": KERNEL_PREFIXES,
    "ChangeGate": CHANGEGATE_PREFIXES,
    "Project Control": PROJECT_CONTROL_PREFIXES,
    "Coordinator": COORDINATOR_PREFIXES,
    "Software Delivery Composition": SOFTWARE_DELIVERY_COMPOSITION_PREFIXES,
    "Adapters": ADAPTER_PREFIXES,
}

# Narrow, documented vendor-SDK root set (ADR-002). Repository inventory found NONE of these
# imported anywhere in agent_core, nor declared in pyproject.toml; the rules are pre-armed for
# future code. Deliberately not expanded into an arbitrary denylist.
VENDOR_SDK_ROOTS = {
    "anthropic",
    "openai",
    "github",
    "gitlab",
    "boto3",
}

ACTIVE = "ACTIVE_AND_EXERCISED"
RESERVED = "RESERVED_BOUNDARY_NOT_YET_INSTANTIATED"


# --- import extraction ------------------------------------------------------

@dataclass(frozen=True)
class ImportEdge:
    """One direct static import: `module` (importer) imports `imported`."""
    path: str      # repo-relative file path of the importing file
    module: str    # dotted module name of the importing file
    imported: str  # dotted module name being imported


def _module_name(path: pathlib.Path) -> str:
    """Dotted module name for a file under the repo root (no import executed)."""
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(importer_module: str, node: ast.ImportFrom, is_package: bool) -> str:
    """Resolve a relative ImportFrom to an absolute dotted module path.

    Relative imports are NOT silently ignored: `from . import x` inside a package resolves
    against the package itself, and inside a module against its parent package.
    """
    base_parts = importer_module.split(".")
    if not is_package:
        base_parts = base_parts[:-1]  # a module's level-1 anchor is its parent package
    # each extra level walks one more package up
    up = node.level - 1
    if up:
        base_parts = base_parts[:-up] if up <= len(base_parts) else []
    if node.module:
        base_parts = base_parts + node.module.split(".")
    return ".".join(p for p in base_parts if p)


def _collect_edges() -> list[ImportEdge]:
    """Parse every agent_core Python file and collect direct static import edges."""
    edges: list[ImportEdge] = []
    if not AGENT_CORE.is_dir():
        return edges
    for path in sorted(AGENT_CORE.rglob("*.py")):
        # skip caches / generated / vendored trees
        if any(part in {"__pycache__", ".venv", "site-packages"} for part in path.parts):
            continue
        importer = _module_name(path)
        is_package = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(ImportEdge(rel, importer, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import
                    target = _resolve_relative(importer, node, is_package)
                else:
                    target = node.module or ""
                if target:
                    edges.append(ImportEdge(rel, importer, target))
    return sorted(edges, key=lambda e: (e.path, e.module, e.imported))


EDGES: list[ImportEdge] = _collect_edges()
SCANNED_MODULES: list[str] = sorted({e.module for e in EDGES} | {
    _module_name(p) for p in sorted(AGENT_CORE.rglob("*.py"))
    if AGENT_CORE.is_dir()
    and not any(part in {"__pycache__", ".venv", "site-packages"} for part in p.parts)
})


def _in_group(module: str, prefixes: tuple[str, ...]) -> bool:
    """True when `module` is exactly a prefix or a dotted descendant of one."""
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _package_exists(prefixes: tuple[str, ...]) -> bool:
    """True when any prefix corresponds to a real directory or module on disk."""
    for prefix in prefixes:
        rel = pathlib.Path(*prefix.split("."))
        if (REPO_ROOT / rel).is_dir() or (REPO_ROOT / rel).with_suffix(".py").is_file():
            return True
    return False


def _files_in_group(prefixes: tuple[str, ...]) -> list[str]:
    return sorted(m for m in SCANNED_MODULES if _in_group(m, prefixes))


def boundary_status(prefixes: tuple[str, ...]) -> str:
    """ACTIVE_AND_EXERCISED when the package exists on disk; otherwise RESERVED."""
    return ACTIVE if _package_exists(prefixes) else RESERVED


def _violations(
    source: tuple[str, ...], forbidden: tuple[str, ...],
) -> list[str]:
    """Deterministically sorted diagnostics for source-group modules importing `forbidden`."""
    out = []
    for e in EDGES:
        if _in_group(e.module, source) and _in_group(e.imported, forbidden):
            out.append(f"{e.path}: {e.module} -> {e.imported}")
    return sorted(out)


def _vendor_violations(source: tuple[str, ...]) -> list[str]:
    out = []
    for e in EDGES:
        if _in_group(e.module, source) and e.imported.split(".")[0] in VENDOR_SDK_ROOTS:
            out.append(f"{e.path}: {e.module} -> {e.imported}")
    return sorted(out)


# --- boundary inventory tests ----------------------------------------------

def test_current_changegate_boundary_is_non_vacuous() -> None:
    """The ChangeGate rules must actually bite: build_harness exists and is scanned."""
    changegate_modules = _files_in_group(CHANGEGATE_PREFIXES)
    assert changegate_modules, "no module classified as ChangeGate; boundary is vacuous"
    assert any(m.startswith("agent_core.build_harness") for m in changegate_modules)
    assert boundary_status(CHANGEGATE_PREFIXES) == ACTIVE


def test_boundary_groups_have_explicit_active_or_reserved_status() -> None:
    for name, prefixes in BOUNDARY_GROUPS.items():
        status = boundary_status(prefixes)
        assert status in {ACTIVE, RESERVED}, f"{name}: unclassified"
        if status == ACTIVE:
            # a package that exists must contribute at least one scanned file
            assert _files_in_group(prefixes), (
                f"{name}: package exists but zero files scanned"
            )


def test_reserved_product_prefixes_do_not_overlap() -> None:
    seen: dict[str, str] = {}
    for name, prefixes in BOUNDARY_GROUPS.items():
        for prefix in prefixes:
            assert prefix not in seen, (
                f"prefix {prefix!r} claimed by both {seen[prefix]!r} and {name!r}"
            )
            seen[prefix] = name
    # no prefix may be a dotted descendant of another group's prefix
    for prefix_a, group_a in seen.items():
        for prefix_b, group_b in seen.items():
            if group_a != group_b and prefix_a.startswith(prefix_b + "."):
                pytest.fail(
                    f"prefix {prefix_a!r} ({group_a}) nests inside {prefix_b!r} ({group_b})"
                )


# --- kernel rules -----------------------------------------------------------

def test_kernel_has_no_outward_product_dependencies() -> None:
    forbidden = (
        CHANGEGATE_PREFIXES + PROJECT_CONTROL_PREFIXES + COORDINATOR_PREFIXES
        + SOFTWARE_DELIVERY_COMPOSITION_PREFIXES + ADAPTER_PREFIXES
    )
    found = _violations(KERNEL_PREFIXES, forbidden)
    assert not found, "kernel/core must not depend on products or adapters:\n" + "\n".join(found)


def test_kernel_does_not_import_vendor_sdks() -> None:
    found = _vendor_violations(KERNEL_PREFIXES)
    assert not found, "kernel/core must be vendor-neutral:\n" + "\n".join(found)


# --- project control rules --------------------------------------------------

def test_project_control_does_not_import_changegate() -> None:
    found = _violations(PROJECT_CONTROL_PREFIXES, CHANGEGATE_PREFIXES)
    assert not found, "project_control -> changegate is forbidden:\n" + "\n".join(found)


def test_project_control_does_not_import_coordinator() -> None:
    found = _violations(PROJECT_CONTROL_PREFIXES, COORDINATOR_PREFIXES)
    assert not found, "project_control -> coordinator is forbidden:\n" + "\n".join(found)


def test_project_control_does_not_import_vendor_adapters() -> None:
    found = _violations(PROJECT_CONTROL_PREFIXES, ADAPTER_PREFIXES)
    assert not found, "project_control -> adapters is forbidden:\n" + "\n".join(found)


def test_project_control_does_not_import_vendor_sdks() -> None:
    found = _vendor_violations(PROJECT_CONTROL_PREFIXES)
    assert not found, "project_control must be vendor-neutral:\n" + "\n".join(found)


# --- coordinator rules ------------------------------------------------------

def test_coordinator_does_not_import_changegate() -> None:
    # both agent_core.changegate and the current agent_core.build_harness count as ChangeGate
    found = _violations(COORDINATOR_PREFIXES, CHANGEGATE_PREFIXES)
    assert not found, "coordinator -> changegate is forbidden:\n" + "\n".join(found)


def test_coordinator_does_not_import_vendor_adapters() -> None:
    found = _violations(COORDINATOR_PREFIXES, ADAPTER_PREFIXES)
    assert not found, "coordinator -> adapters is forbidden:\n" + "\n".join(found)


def test_coordinator_does_not_import_vendor_sdks() -> None:
    found = _vendor_violations(COORDINATOR_PREFIXES)
    assert not found, "coordinator must be vendor-neutral:\n" + "\n".join(found)


# --- changegate rules -------------------------------------------------------

def test_changegate_does_not_import_coordinator() -> None:
    found = _violations(CHANGEGATE_PREFIXES, COORDINATOR_PREFIXES)
    assert not found, (
        "changegate -> coordinator is forbidden (ChangeGate must ship standalone):\n"
        + "\n".join(found)
    )


# --- composition rule -------------------------------------------------------

def test_only_software_delivery_composition_may_import_both_coordinator_and_changegate() -> None:
    """Any module importing BOTH a Coordinator and a ChangeGate module must be composition."""
    coordinator_importers = {
        e.module for e in EDGES if _in_group(e.imported, COORDINATOR_PREFIXES)
    }
    changegate_importers = {
        e.module for e in EDGES if _in_group(e.imported, CHANGEGATE_PREFIXES)
    }
    knows_both = coordinator_importers & changegate_importers
    offenders = sorted(
        m for m in knows_both
        if not _in_group(m, SOFTWARE_DELIVERY_COMPOSITION_PREFIXES)
    )
    assert not offenders, (
        "only the software-delivery composition layer may know both Coordinator and "
        "ChangeGate:\n" + "\n".join(offenders)
    )
