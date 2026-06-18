"""Template contract loader and validator.

This module exposes a small, dependency-free loader for the per-template
``manifest.json`` files that ship inside ``templates/<template_id>/`` and
describes the rendering contract the template promises (schema version,
template file location, required payload paths, singleton placeholders,
allowed chart modes).

The loader purposefully does not consult the rendered docx or the payload --
those are the responsibility of ``scripts/template_preflight.py`` (Task 3) and
``scripts/render_from_template.py``. Keeping this module narrowly scoped lets
the rest of the pipeline depend on a stable ``TemplateContract`` object
regardless of how the renderer evolves.

Stable error codes (see ``ContractError.code``)::

    INVALID_MANIFEST            - JSON is malformed or required fields missing
    UNSUPPORTED_SCHEMA_VERSION  - schema_version is not in SUPPORTED_SCHEMAS
    TEMPLATE_NOT_FOUND          - template_file does not resolve to an existing
                                  file inside the manifest directory tree
    PATH_ESCAPE                 - template_file resolves outside its manifest
                                  directory's repo root
    INVALID_TEMPLATE_TYPE       - template_type is not a known value
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SCHEMAS: frozenset[int] = frozenset({1})

# Allowed values for ``template_type``. New types may be added here as new
# template families are introduced; unknown values must be rejected so that
# downstream tooling can rely on the value matching a known renderer contract.
KNOWN_TEMPLATE_TYPES: frozenset[str] = frozenset(
    {"patient-questionnaire-report"}
)

REQUIRED_TOP_LEVEL_FIELDS: tuple[str, ...] = (
    "schema_version",
    "template_id",
    "template_type",
    "template_file",
    "renderer",
)


class ContractError(ValueError):
    """Raised when a template manifest violates the contract."""

    def __init__(self, code: str, message: str, *, manifest_path: Path | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.manifest_path = manifest_path


@dataclass(frozen=True)
class TemplateContract:
    """In-memory representation of a validated ``manifest.json``."""

    schema_version: int
    template_id: str
    template_type: str
    template_path: Path
    renderer: str
    required_payload_paths: tuple[str, ...] = ()
    required_singletons: tuple[str, ...] = ()
    optional_singletons: tuple[str, ...] = ()
    # Placeholders that are allowed to appear zero or more times in the
    # template. Used to whitelist legitimate repeat occurrences such as
    # ``{{field.service.unit}}`` on the cover and settlement pages.
    field_placeholders: tuple[str, ...] = ()
    allowed_chart_modes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    manifest_path: Path = field(default_factory=lambda: Path("."))


def _ensure_str_list(value: Any, field_name: str, manifest_path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContractError(
            "INVALID_MANIFEST",
            f"{field_name} must be a list of strings",
            manifest_path=manifest_path,
        )
    return tuple(value)


def _ensure_chart_modes(value: Any, manifest_path: Path) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContractError(
            "INVALID_MANIFEST",
            "allowed_chart_modes must be an object",
            manifest_path=manifest_path,
        )
    result: dict[str, tuple[str, ...]] = {}
    for key, modes in value.items():
        if not isinstance(key, str):
            raise ContractError(
                "INVALID_MANIFEST",
                "allowed_chart_modes keys must be strings",
                manifest_path=manifest_path,
            )
        if not isinstance(modes, list) or not all(isinstance(m, str) for m in modes):
            raise ContractError(
                "INVALID_MANIFEST",
                f"allowed_chart_modes[{key}] must be a list of strings",
                manifest_path=manifest_path,
            )
        result[key] = tuple(modes)
    return result


def _resolve_template_path(manifest_path: Path, template_file: str) -> Path:
    """Resolve ``template_file`` relative to the manifest directory.

    The resolved path is required to live somewhere under the manifest
    directory's nearest ancestor that contains the manifest itself, to prevent
    a manifest from pointing at an arbitrary file on disk
    (``../../etc/passwd``). For our layout that ancestor is the repository's
    ``templates/`` directory; we use the manifest's parent's parent as a
    practical lower bound that still lets a manifest live inside
    ``templates/<id>/`` and reference ``../shared.docx``.
    """
    manifest_dir = manifest_path.parent.resolve()
    repo_templates_root = manifest_dir.parent.resolve()
    candidate = (manifest_dir / template_file).resolve()
    try:
        candidate.relative_to(repo_templates_root)
    except ValueError as exc:
        raise ContractError(
            "PATH_ESCAPE",
            f"template_file resolves outside templates root: {candidate}",
            manifest_path=manifest_path,
        ) from exc
    if not candidate.is_file():
        raise ContractError(
            "TEMPLATE_NOT_FOUND",
            f"template_file does not exist: {candidate}",
            manifest_path=manifest_path,
        )
    return candidate


def load_manifest(manifest_path: Path) -> TemplateContract:
    """Load and validate a template manifest from disk.

    Raises :class:`ContractError` on any contract violation. Stable
    ``ContractError.code`` values are documented at module level.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise ContractError(
            "INVALID_MANIFEST",
            f"manifest file not found: {manifest_path}",
            manifest_path=manifest_path,
        )

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(
            "INVALID_MANIFEST",
            f"manifest is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            manifest_path=manifest_path,
        ) from exc

    if not isinstance(raw, dict):
        raise ContractError(
            "INVALID_MANIFEST",
            "manifest root must be a JSON object",
            manifest_path=manifest_path,
        )

    missing = [name for name in REQUIRED_TOP_LEVEL_FIELDS if name not in raw]
    if missing:
        raise ContractError(
            "INVALID_MANIFEST",
            f"missing required field(s): {', '.join(missing)}",
            manifest_path=manifest_path,
        )

    schema_version = raw["schema_version"]
    if not isinstance(schema_version, int) or schema_version not in SUPPORTED_SCHEMAS:
        raise ContractError(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"schema_version={schema_version!r} not in supported set {sorted(SUPPORTED_SCHEMAS)}",
            manifest_path=manifest_path,
        )

    template_type = raw["template_type"]
    if template_type not in KNOWN_TEMPLATE_TYPES:
        raise ContractError(
            "INVALID_TEMPLATE_TYPE",
            f"template_type={template_type!r} not in {sorted(KNOWN_TEMPLATE_TYPES)}",
            manifest_path=manifest_path,
        )

    template_id = raw["template_id"]
    renderer = raw["renderer"]
    if not isinstance(template_id, str) or not template_id.strip():
        raise ContractError(
            "INVALID_MANIFEST",
            "template_id must be a non-empty string",
            manifest_path=manifest_path,
        )
    if not isinstance(renderer, str) or ":" not in renderer:
        raise ContractError(
            "INVALID_MANIFEST",
            "renderer must be a 'module.path:Symbol' string",
            manifest_path=manifest_path,
        )

    template_file = raw["template_file"]
    if not isinstance(template_file, str) or not template_file.strip():
        raise ContractError(
            "INVALID_MANIFEST",
            "template_file must be a non-empty string",
            manifest_path=manifest_path,
        )
    template_path = _resolve_template_path(manifest_path, template_file)

    required_payload_paths = _ensure_str_list(
        raw.get("required_payload_paths"), "required_payload_paths", manifest_path
    )
    required_singletons = _ensure_str_list(
        raw.get("required_singletons"), "required_singletons", manifest_path
    )
    optional_singletons = _ensure_str_list(
        raw.get("optional_singletons"), "optional_singletons", manifest_path
    )
    field_placeholders = _ensure_str_list(
        raw.get("field_placeholders"), "field_placeholders", manifest_path
    )

    overlap = set(required_singletons) & set(optional_singletons)
    if overlap:
        raise ContractError(
            "INVALID_MANIFEST",
            f"singletons appear in both required and optional: {sorted(overlap)}",
            manifest_path=manifest_path,
        )

    allowed_chart_modes = _ensure_chart_modes(
        raw.get("allowed_chart_modes"), manifest_path
    )

    return TemplateContract(
        schema_version=schema_version,
        template_id=template_id,
        template_type=template_type,
        template_path=template_path,
        renderer=renderer,
        required_payload_paths=required_payload_paths,
        required_singletons=required_singletons,
        optional_singletons=optional_singletons,
        field_placeholders=field_placeholders,
        allowed_chart_modes=allowed_chart_modes,
        manifest_path=manifest_path.resolve(),
    )


def iter_known_template_types() -> Iterable[str]:
    """Public accessor for downstream code that wants to display valid types."""
    return iter(sorted(KNOWN_TEMPLATE_TYPES))
