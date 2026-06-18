#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

try:
    from .build_payload import build_payload, parse_markdown_content, validate_payload, PreflightError, preflight_report_content, load_dimension_library
    from .final_validate_docx import FinalValidationError, validate_docx
    from .parse_questionnaire import parse_sheet
    from .render_from_template import TemplateRenderer
    from .template_contract import ContractError, load_manifest
    from .template_preflight import TemplatePreflightError, preflight_template
except ImportError:
    from build_payload import build_payload, parse_markdown_content, validate_payload, PreflightError, preflight_report_content, load_dimension_library
    from final_validate_docx import FinalValidationError, validate_docx
    from parse_questionnaire import parse_sheet
    from render_from_template import TemplateRenderer
    from template_contract import ContractError, load_manifest
    from template_preflight import TemplatePreflightError, preflight_template


ROOT = Path(__file__).resolve().parents[1]


# Ordered phase names recorded in run_manifest.json/timings.json. Keep stable so
# downstream perf comparisons can read them by key.
PHASE_NAMES = (
    "parse_questionnaire",
    "preflight_content",
    "build_payload",
    "template_preflight",
    "render_docx",
    "final_validate_docx",
    "total",
)


class PipelineFinalValidationError(RuntimeError):
    """Raised when the rendered docx fails final validation.

    Unlike the previous warning-only behaviour, this error indicates that the
    final docx has been removed and must NOT be delivered. The run directory is
    retained on disk so the caller can inspect ``final_validation_error.json``
    and the partially-built artifacts.
    """

    def __init__(self, message: str, run_dir: Path) -> None:
        super().__init__(message)
        self.run_dir = run_dir


class PhaseTimer:
    """Collect elapsed wall-clock seconds per pipeline phase.

    Usage::

        timer = PhaseTimer()
        with timer.phase("render_docx"):
            ...
        timer.record_total(start)
        timer.as_dict()  # {phase: seconds, ...}
    """

    def __init__(self) -> None:
        self._timings: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        if name not in PHASE_NAMES:
            raise ValueError(f"unknown phase name: {name}")
        start = time.perf_counter()
        try:
            yield
        finally:
            self._timings[name] = round(time.perf_counter() - start, 6)

    def record_total(self, start: float) -> None:
        self._timings["total"] = round(time.perf_counter() - start, 6)

    def as_dict(self) -> dict[str, float]:
        return dict(self._timings)


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "report"


def default_run_dir(questionnaire_path: Path, content_path: Path) -> Path:
    seed = f"{questionnaire_path.resolve()}|{content_path.resolve()}|{datetime.now().isoformat()}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = slugify(questionnaire_path.stem)
    return ROOT / "tmp" / "runs" / f"{stamp}-{stem}-{digest}"


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_info(path: Path) -> dict:
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "mtime": stat.st_mtime,
        "sha1": file_sha1(resolved),
    }


def finalize_with_validation(output_docx: Path, payload: dict, run_dir: Path) -> None:
    """Run final validation and enforce fail-fast removal of the output docx.

    On validation failure this function:
      * deletes ``output_docx`` so it cannot be mistaken for a deliverable,
      * writes ``run_dir/final_validation_error.json`` with the error message,
      * raises :class:`PipelineFinalValidationError`.

    On success the docx is left in place and no error file is written.
    """
    try:
        validate_docx(output_docx, payload)
    except FinalValidationError as exc:
        message = str(exc)
        error_path = run_dir / "final_validation_error.json"
        error_path.write_text(
            json.dumps(
                {
                    "error": message,
                    "output_docx": str(output_docx.resolve()),
                    "run_dir": str(run_dir.resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            output_docx.unlink()
        except FileNotFoundError:
            pass
        raise PipelineFinalValidationError(message, run_dir) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the patient report pipeline in an isolated per-run directory.")
    parser.add_argument("questionnaire_xlsx")
    parser.add_argument("report_content")
    parser.add_argument("--run-dir")
    parser.add_argument("--output-docx")
    parser.add_argument("--product")
    parser.add_argument("--region")
    parser.add_argument("--time")
    parser.add_argument("--attachment-name")
    parser.add_argument("--survey-period")
    parser.add_argument("--sample-size")
    parser.add_argument("--valid-count")
    parser.add_argument("--disclaimer-unit")
    args = parser.parse_args()

    questionnaire_path = Path(args.questionnaire_xlsx)
    report_content_path = Path(args.report_content)
    run_dir = Path(args.run_dir) if args.run_dir else default_run_dir(questionnaire_path, report_content_path)
    run_dir.mkdir(parents=True, exist_ok=False)

    timer = PhaseTimer()
    total_start = time.perf_counter()

    with timer.phase("parse_questionnaire"):
        questionnaire = parse_sheet(questionnaire_path)
        questionnaire_json = run_dir / "questionnaire.json"
        questionnaire_json.write_text(json.dumps(questionnaire, ensure_ascii=False, indent=2), encoding="utf-8")

    meta, content = parse_markdown_content(report_content_path)

    # ── Preflight: validate draft completeness before expensive build ──
    with timer.phase("preflight_content"):
        library = load_dimension_library()
        try:
            preflight_result = preflight_report_content(
                meta, content,
                library=library,
                questionnaire=questionnaire,
            )
        except PreflightError as exc:
            print(str(exc), file=sys.stderr)
            print(f"Run directory retained for diagnosis: {run_dir.resolve()}", file=sys.stderr)
            preflight_json = run_dir / "preflight.json"
            preflight_json.write_text(json.dumps(exc.result, ensure_ascii=False, indent=2), encoding="utf-8")
            sys.exit(1)

        preflight_json = run_dir / "preflight.json"
        preflight_json.write_text(json.dumps(preflight_result, ensure_ascii=False, indent=2), encoding="utf-8")

    with timer.phase("build_payload"):
        payload = build_payload(questionnaire, meta, content, args)
        validate_payload(payload)

        payload_json = run_dir / "report_payload.json"
        payload_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # template_preflight: load the bundled manifest and validate the rendered
    # contract against payload + template docx. While Tasks 5-8 are still
    # injecting placeholders, run in 'warning' mode so any contract gap is
    # written to template_preflight.json without aborting the render. Once
    # all placeholders are migrated this should be flipped to 'fail'.
    with timer.phase("template_preflight"):
        manifest_path = ROOT / "templates" / "efficacy" / "manifest.json"
        template_preflight_json = run_dir / "template_preflight.json"
        try:
            contract = load_manifest(manifest_path)
            preflight_doc = preflight_template(contract, payload, mode="warning")
        except ContractError as exc:
            preflight_doc = {
                "status": "error",
                "mode": "warning",
                "errors": [{"code": exc.code, "message": str(exc)}],
                "warnings": [],
            }
            print(f"TEMPLATE_PREFLIGHT_WARNING: {exc}", file=sys.stderr)
        template_preflight_json.write_text(
            json.dumps(preflight_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if preflight_doc.get("errors"):
            print(
                f"TEMPLATE_PREFLIGHT_WARNING: {len(preflight_doc['errors'])} issue(s); see "
                f"{template_preflight_json.resolve()}",
                file=sys.stderr,
            )

    output_docx = Path(args.output_docx) if args.output_docx else run_dir / "report.docx"
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    with timer.phase("render_docx"):
        TemplateRenderer(Path(payload["meta"]["template_doc"]), payload).render(output_docx)

    timings_partial = timer.as_dict()
    manifest = {
        "skill_root": str(ROOT.resolve()),
        "run_dir": str(run_dir.resolve()),
        "scripts": {
            "run_report_pipeline": file_info(Path(__file__)),
            "build_payload": file_info(ROOT / "scripts" / "build_payload.py"),
            "render_from_template": file_info(ROOT / "scripts" / "render_from_template.py"),
            "final_validate_docx": file_info(ROOT / "scripts" / "final_validate_docx.py"),
        },
        "template_doc": file_info(Path(payload["meta"]["template_doc"])),
        "inputs": {
            "questionnaire_xlsx": file_info(questionnaire_path),
            "report_content": file_info(report_content_path),
        },
        "artifacts": {
            "questionnaire_json": file_info(questionnaire_json),
            "payload_json": file_info(payload_json),
            "output_docx": str(output_docx.resolve()),
        },
        # Timings recorded so far. The final_validate_docx phase is appended
        # after validation completes so that callers can distinguish
        # render-only vs. render+validate cost.
        "timings_seconds": timings_partial,
    }
    manifest_json = run_dir / "run_manifest.json"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        with timer.phase("final_validate_docx"):
            finalize_with_validation(output_docx, payload, run_dir)
    except PipelineFinalValidationError as exc:
        timer.record_total(total_start)
        manifest["timings_seconds"] = timer.as_dict()
        manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "timings.json").write_text(
            json.dumps(timer.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"FINAL_VALIDATION_ERROR: {exc}", file=sys.stderr)
        print(f"Run diagnostics retained at: {run_dir.resolve()}", file=sys.stderr)
        sys.exit(2)

    timer.record_total(total_start)
    manifest["timings_seconds"] = timer.as_dict()
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "timings.json").write_text(
        json.dumps(timer.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(output_docx.resolve())


if __name__ == "__main__":
    main()
