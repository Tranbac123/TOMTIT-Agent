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
import re
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


@dataclass(frozen=True)
class PrefixStatus:
    """Existence and scan coverage for one declared product prefix."""
    group: str
    prefix: str
    path: pathlib.Path
    scanned_count: int
    status: str


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
    # Each extra level walks one more package up. Reject a depth that would escape the
    # importer's top-level package instead of turning it into an unrelated absolute name.
    up = node.level - 1
    if up >= len(base_parts):
        raise ValueError(
            f"invalid relative import depth {node.level} for {importer_module!r}"
        )
    if up:
        base_parts = base_parts[:-up]
    if node.module:
        base_parts = base_parts + node.module.split(".")
    return ".".join(p for p in base_parts if p)


def _import_from_targets(
    importer_module: str, node: ast.ImportFrom, is_package: bool,
) -> tuple[str, ...]:
    """Conservative absolute targets for one ``ImportFrom`` statement.

    The base remains an edge because importing a member executes/loads that module. Every
    non-star alias is also an edge so package-member imports cannot hide a product boundary.
    """
    base = (
        _resolve_relative(importer_module, node, is_package)
        if node.level
        else (node.module or "")
    )
    targets = {base} if base else set()
    if base:
        targets.update(
            f"{base}.{alias.name}" for alias in node.names if alias.name != "*"
        )
    return tuple(sorted(targets))


def _extract_edges(
    source: str, *, path: str, importer: str, is_package: bool,
) -> list[ImportEdge]:
    """Extract direct static imports from source without importing the parsed module."""
    edges: set[ImportEdge] = set()
    tree = ast.parse(source, filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                edges.add(ImportEdge(path, importer, alias.name))
        elif isinstance(node, ast.ImportFrom):
            try:
                targets = _import_from_targets(importer, node, is_package)
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            for target in targets:
                edges.add(ImportEdge(path, importer, target))
    return sorted(edges, key=lambda e: (e.path, e.module, e.imported))


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
        rel = str(path.relative_to(REPO_ROOT))
        edges.extend(_extract_edges(
            path.read_text(encoding="utf-8"),
            path=rel,
            importer=importer,
            is_package=is_package,
        ))
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


def _files_in_group(prefixes: tuple[str, ...]) -> list[str]:
    return sorted(m for m in SCANNED_MODULES if _in_group(m, prefixes))


def _prefix_status(
    group: str,
    prefix: str,
    *,
    repo_root: pathlib.Path,
    scanned_modules: list[str],
) -> PrefixStatus:
    """Classify one prefix, rejecting an existing prefix with no scanned module."""
    relative = pathlib.Path(*prefix.split("."))
    package_path = (repo_root / relative).resolve()
    module_path = package_path.with_suffix(".py")
    exists = package_path.is_dir() or module_path.is_file()
    resolved_path = package_path if package_path.is_dir() or not module_path.is_file() else module_path
    scanned_count = sum(_in_group(module, (prefix,)) for module in scanned_modules)
    if exists and scanned_count == 0:
        raise AssertionError(
            f"{group}: prefix {prefix!r}; resolved filesystem path={resolved_path}; "
            "scanned count=0; expected invariant: every existing declared prefix must "
            "contribute at least one scanned Python module"
        )
    return PrefixStatus(
        group=group,
        prefix=prefix,
        path=resolved_path,
        scanned_count=scanned_count,
        status=ACTIVE if exists else RESERVED,
    )


def boundary_prefix_statuses(
    group: str,
    prefixes: tuple[str, ...],
    *,
    repo_root: pathlib.Path = REPO_ROOT,
    scanned_modules: list[str] | None = None,
) -> tuple[PrefixStatus, ...]:
    """Validate and classify every prefix independently, in declaration order."""
    modules = SCANNED_MODULES if scanned_modules is None else scanned_modules
    return tuple(
        _prefix_status(
            group, prefix, repo_root=repo_root, scanned_modules=modules,
        )
        for prefix in prefixes
    )


def boundary_status(
    prefixes: tuple[str, ...],
    *,
    group: str = "Boundary group",
    repo_root: pathlib.Path = REPO_ROOT,
    scanned_modules: list[str] | None = None,
) -> str:
    """Summarize a group only after every declared prefix passes coverage validation."""
    statuses = boundary_prefix_statuses(
        group, prefixes, repo_root=repo_root, scanned_modules=scanned_modules,
    )
    return ACTIVE if any(item.status == ACTIVE for item in statuses) else RESERVED


def _violations(
    source: tuple[str, ...], forbidden: tuple[str, ...], *, edges: list[ImportEdge] | None = None,
) -> list[str]:
    """Deterministically sorted diagnostics for source-group modules importing `forbidden`."""
    out = []
    for e in EDGES if edges is None else edges:
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
    assert boundary_status(CHANGEGATE_PREFIXES, group="ChangeGate") == ACTIVE


def test_boundary_groups_have_explicit_active_or_reserved_status() -> None:
    for name, prefixes in BOUNDARY_GROUPS.items():
        prefix_statuses = boundary_prefix_statuses(name, prefixes)
        status = boundary_status(prefixes, group=name)
        assert status in {ACTIVE, RESERVED}, f"{name}: unclassified"
        assert all(item.status in {ACTIVE, RESERVED} for item in prefix_statuses)


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


# --- adversarial parser regression tests -----------------------------------

@pytest.mark.parametrize(
    ("source", "importer", "is_package", "expected"),
    [
        (
            "from agent_core import coordinator",
            "probe.worker",
            False,
            {"agent_core", "agent_core.coordinator"},
        ),
        (
            "from agent_core import build_harness",
            "probe.worker",
            False,
            {"agent_core", "agent_core.build_harness"},
        ),
        (
            "from . import helpers",
            "agent_core.coordinator.worker",
            False,
            {"agent_core.coordinator", "agent_core.coordinator.helpers"},
        ),
        (
            "from .. import build_harness",
            "agent_core.coordinator.worker",
            False,
            {"agent_core", "agent_core.build_harness"},
        ),
        (
            "from ..build_harness import api",
            "agent_core.coordinator.worker",
            False,
            {"agent_core.build_harness", "agent_core.build_harness.api"},
        ),
        (
            "from ... import baz",
            "agent_core.coordinator.deep.worker",
            False,
            {"agent_core", "agent_core.baz"},
        ),
        (
            "from package import *",
            "probe.worker",
            False,
            {"package"},
        ),
    ],
)
def test_import_from_targets_preserve_base_and_non_star_aliases(
    source: str,
    importer: str,
    is_package: bool,
    expected: set[str],
) -> None:
    edges = _extract_edges(
        source, path="synthetic.py", importer=importer, is_package=is_package,
    )
    assert {edge.imported for edge in edges} == expected


def test_invalid_relative_depth_is_not_reinterpreted_as_absolute() -> None:
    with pytest.raises(ValueError, match="invalid relative import depth"):
        _extract_edges(
            "from ... import escaped",
            path="agent_core/worker.py",
            importer="agent_core.worker",
            is_package=False,
        )


def test_prefix_matching_is_segment_aware() -> None:
    assert _in_group(
        "agent_core.build_harness.api", ("agent_core.build_harness",),
    )
    assert not _in_group(
        "agent_core.build_harness_extra", ("agent_core.build_harness",),
    )


def test_coordinator_package_member_relative_import_is_forbidden_end_to_end() -> None:
    edges = _extract_edges(
        "from .. import build_harness",
        path="agent_core/coordinator/worker.py",
        importer="agent_core.coordinator.worker",
        is_package=False,
    )
    assert _violations(
        COORDINATOR_PREFIXES, CHANGEGATE_PREFIXES, edges=edges,
    ) == [
        "agent_core/coordinator/worker.py: agent_core.coordinator.worker -> "
        "agent_core.build_harness"
    ]


def test_coordinator_package_member_adapter_import_is_forbidden_end_to_end() -> None:
    edges = _extract_edges(
        "from agent_core import adapters",
        path="agent_core/coordinator/worker.py",
        importer="agent_core.coordinator.worker",
        is_package=False,
    )
    assert _violations(COORDINATOR_PREFIXES, ADAPTER_PREFIXES, edges=edges)


def test_unauthorized_package_member_importer_knowing_both_products_is_detected() -> None:
    edges = _extract_edges(
        "from agent_core import coordinator, build_harness",
        path="agent_core/rogue.py",
        importer="agent_core.rogue",
        is_package=False,
    )
    coordinator_importers = {
        edge.module for edge in edges
        if _in_group(edge.imported, COORDINATOR_PREFIXES)
    }
    changegate_importers = {
        edge.module for edge in edges
        if _in_group(edge.imported, CHANGEGATE_PREFIXES)
    }
    offenders = sorted(
        module for module in coordinator_importers & changegate_importers
        if not _in_group(module, SOFTWARE_DELIVERY_COMPOSITION_PREFIXES)
    )
    assert offenders == ["agent_core.rogue"]


# --- per-prefix coverage regression tests ----------------------------------

def _make_prefix_path(root: pathlib.Path, prefix: str, *, module_file: bool = False) -> pathlib.Path:
    path = root.joinpath(*prefix.split("."))
    if module_file:
        path = path.with_suffix(".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path


def test_absent_prefix_is_reserved(tmp_path: pathlib.Path) -> None:
    status = boundary_prefix_statuses(
        "Example", ("agent_core.absent",), repo_root=tmp_path, scanned_modules=[],
    )[0]
    assert (status.status, status.scanned_count) == (RESERVED, 0)


def test_existing_package_init_is_active(tmp_path: pathlib.Path) -> None:
    package = _make_prefix_path(tmp_path, "agent_core.present")
    (package / "__init__.py").write_text("", encoding="utf-8")
    status = boundary_prefix_statuses(
        "Example", ("agent_core.present",),
        repo_root=tmp_path,
        scanned_modules=["agent_core.present"],
    )[0]
    assert (status.status, status.scanned_count) == (ACTIVE, 1)


def test_existing_module_file_is_active(tmp_path: pathlib.Path) -> None:
    _make_prefix_path(tmp_path, "agent_core.present", module_file=True)
    status = boundary_prefix_statuses(
        "Example", ("agent_core.present",),
        repo_root=tmp_path,
        scanned_modules=["agent_core.present"],
    )[0]
    assert status.status == ACTIVE
    assert status.path == (tmp_path / "agent_core/present.py").resolve()


def test_existing_empty_directory_is_invalid(tmp_path: pathlib.Path) -> None:
    path = _make_prefix_path(tmp_path, "agent_core.empty")
    with pytest.raises(AssertionError) as caught:
        boundary_prefix_statuses(
            "Example", ("agent_core.empty",), repo_root=tmp_path, scanned_modules=[],
        )
    message = str(caught.value)
    assert "Example" in message
    assert "agent_core.empty" in message
    assert str(path.resolve()) in message
    assert "scanned count=0" in message
    assert "every existing declared prefix" in message


def test_populated_sibling_cannot_mask_empty_changegate_prefix(
    tmp_path: pathlib.Path,
) -> None:
    _make_prefix_path(tmp_path, "agent_core.changegate")
    _make_prefix_path(tmp_path, "agent_core.build_harness")
    with pytest.raises(AssertionError, match="agent_core.changegate"):
        boundary_status(
            CHANGEGATE_PREFIXES,
            group="ChangeGate",
            repo_root=tmp_path,
            scanned_modules=["agent_core.build_harness.api"],
        )


def test_absent_sibling_plus_active_sibling_is_valid(tmp_path: pathlib.Path) -> None:
    _make_prefix_path(tmp_path, "agent_core.build_harness")
    statuses = boundary_prefix_statuses(
        "ChangeGate",
        CHANGEGATE_PREFIXES,
        repo_root=tmp_path,
        scanned_modules=["agent_core.build_harness.api"],
    )
    assert [item.status for item in statuses] == [RESERVED, ACTIVE]
    assert boundary_status(
        CHANGEGATE_PREFIXES,
        group="ChangeGate",
        repo_root=tmp_path,
        scanned_modules=["agent_core.build_harness.api"],
    ) == ACTIVE


def test_two_active_sibling_prefixes_are_valid(tmp_path: pathlib.Path) -> None:
    for prefix in CHANGEGATE_PREFIXES:
        _make_prefix_path(tmp_path, prefix)
    statuses = boundary_prefix_statuses(
        "ChangeGate",
        CHANGEGATE_PREFIXES,
        repo_root=tmp_path,
        scanned_modules=["agent_core.changegate", "agent_core.build_harness.api"],
    )
    assert [item.status for item in statuses] == [ACTIVE, ACTIVE]


def test_group_summary_does_not_conceal_invalid_prefix(tmp_path: pathlib.Path) -> None:
    for prefix in CHANGEGATE_PREFIXES:
        _make_prefix_path(tmp_path, prefix)
    with pytest.raises(AssertionError, match="scanned count=0"):
        boundary_status(
            CHANGEGATE_PREFIXES,
            group="ChangeGate",
            repo_root=tmp_path,
            scanned_modules=["agent_core.changegate.api"],
        )


def test_composition_prefix_pair_uses_same_per_prefix_rule(tmp_path: pathlib.Path) -> None:
    for prefix in SOFTWARE_DELIVERY_COMPOSITION_PREFIXES:
        _make_prefix_path(tmp_path, prefix)
    with pytest.raises(
        AssertionError, match="agent_core.software_delivery_workflow",
    ):
        boundary_status(
            SOFTWARE_DELIVERY_COMPOSITION_PREFIXES,
            group="Software Delivery Composition",
            repo_root=tmp_path,
            scanned_modules=["agent_core.workflows.software_delivery.runner"],
        )


def test_prefix_coverage_diagnostic_is_deterministic(tmp_path: pathlib.Path) -> None:
    _make_prefix_path(tmp_path, "agent_core.empty")

    def diagnostic() -> str:
        with pytest.raises(AssertionError) as caught:
            boundary_prefix_statuses(
                "Example", ("agent_core.empty",),
                repo_root=tmp_path,
                scanned_modules=[],
            )
        return str(caught.value)

    assert diagnostic() == diagnostic()


# --- ADR-003 inventory regression test -------------------------------------

def test_adr_003_decision_inventory_and_stated_counts_match_repository() -> None:
    adr_path = (
        REPO_ROOT / "docs/architecture/ADR-003-canonical-ownership-and-monorepo-boundaries.md"
    )
    text = adr_path.read_text(encoding="utf-8")
    decision_row = next(
        (line for line in text.splitlines() if line.startswith("| Decision |")),
        "",
    )
    decision_classes = {
        "ChangeGateDecision": REPO_ROOT / "agent_core/build_harness/change_gate.py",
        "ProcessGuardDecision": REPO_ROOT / "agent_core/build_harness/process_guard.py",
        "PolicyDecision": REPO_ROOT / "agent_core/safety/policy.py",
        "ApprovalDecision": REPO_ROOT / "agent_core/safety/approval.py",
        "SafetyDecision": REPO_ROOT / "agent_core/safety/capability_gate.py",
        "ConfirmedDecision": REPO_ROOT / "agent_core/confirmation/models.py",
    }
    omitted: list[str] = []
    for class_name, source_path in decision_classes.items():
        class_names = {
            node.name
            for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ClassDef)
        }
        assert class_name in class_names, (
            f"repository decision class {class_name} missing from {source_path}"
        )
        if class_name not in decision_row:
            omitted.append(class_name)
    assert not omitted, f"ADR-003 Decision row omits semantic classes: {omitted}"
    assert "SaveDecisionArgs" not in decision_row, (
        "ADR-003 must not count SaveDecisionArgs as a semantic Decision"
    )

    statuses = ("EXISTS", "DOMAIN_SPECIFIC_EXISTING", "FUTURE_CONCEPT_NOT_IMPLEMENTED")
    table_counts = {status: 0 for status in statuses}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[1] in table_counts:
            table_counts[cells[1]] += 1

    stated_counts = {
        status: int(count)
        for status, count in re.findall(
            r"^- `(EXISTS|DOMAIN_SPECIFIC_EXISTING|FUTURE_CONCEPT_NOT_IMPLEMENTED)`: (\d+)$",
            text,
            flags=re.MULTILINE,
        )
    }
    assert stated_counts == table_counts, (
        "ADR-003 stated inventory counts disagree with its concept table: "
        f"stated={stated_counts}, table={table_counts}"
    )
