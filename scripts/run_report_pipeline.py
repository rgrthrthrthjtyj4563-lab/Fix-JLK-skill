#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from .build_payload import build_payload, parse_markdown_content, validate_payload
    from .final_validate_docx import FinalValidationError, validate_docx
    from .parse_questionnaire import parse_sheet
    from .render_from_template import TemplateRenderer
except ImportError:
    from build_payload import build_payload, parse_markdown_content, validate_payload
    from final_validate_docx import FinalValidationError, validate_docx
    from parse_questionnaire import parse_sheet
    from render_from_template import TemplateRenderer


ROOT = Path(__file__).resolve().parents[1]


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the patient report pipeline in an isolated per-run directory.")
    parser.add_argument("questionnaire_xlsx")
    parser.add_argument("report_content")
    parser.add_argument("--run-dir")
    parser.add_argument("--output-docx")
    parser.add_argument("--product")
    parser.add_argument("--region")
    parser.add_argument("--time")
    parser.add_argument("--theme")
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

    questionnaire = parse_sheet(questionnaire_path)
    questionnaire_json = run_dir / "questionnaire.json"
    questionnaire_json.write_text(json.dumps(questionnaire, ensure_ascii=False, indent=2), encoding="utf-8")

    meta, content = parse_markdown_content(report_content_path)
    payload = build_payload(questionnaire, meta, content, args)
    validate_payload(payload)

    payload_json = run_dir / "report_payload.json"
    payload_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output_docx = Path(args.output_docx) if args.output_docx else run_dir / "report.docx"
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    TemplateRenderer(Path(payload["meta"]["template_doc"]), payload).render(output_docx)

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
    }
    manifest_json = run_dir / "run_manifest.json"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        validate_docx(output_docx, payload)
    except FinalValidationError as exc:
        print(f"FINAL_VALIDATION_WARNING: {exc}", file=sys.stderr)
        print(f"Run diagnostics retained at: {run_dir.resolve()}", file=sys.stderr)
        # Keep output for debugging

    print(output_docx.resolve())


if __name__ == "__main__":
    main()
