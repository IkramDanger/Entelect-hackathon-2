"""Build a verified, reproducible Age of Enteland submission.

The planner is deliberately treated as an external program.  This keeps the
harness independent of solver internals and, more importantly, verifies the
same command-line pipeline that is shipped in the source archive.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / ".claude" / "skills" / "enteland-optimizer" / "scripts"
PLANNER = SCRIPTS / "plan.py"
ENGINE = SCRIPTS / "engine.py"

# These files are sufficient to recreate the planner environment and rerun the
# exact level packaged.  Repository-relative archive names preserve the paths
# expected by plan.py and engine.find_resources().
COMMON_SOURCE_FILES = (
    Path("lane_H.py"),
    Path("requirements.txt"),
    Path("README.md"),
    Path("supporting-resources/resources.json"),
    Path(".claude/skills/enteland-optimizer/scripts/plan.py"),
    Path(".claude/skills/enteland-optimizer/scripts/route.py"),
    Path(".claude/skills/enteland-optimizer/scripts/engine.py"),
    Path(".claude/skills/enteland-optimizer/scripts/build.py"),
)


class SubmissionError(RuntimeError):
    """A verification failure which must prevent publication."""


def _run(command: List[str], label: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip() or "no output"
        raise SubmissionError(f"{label} failed (exit {result.returncode}):\n{details}")
    return result


def _generate(level_path: Path, level_num: int, output_path: Path) -> None:
    _run(
        [
            sys.executable,
            str(PLANNER),
            "--level",
            str(level_path),
            "--level-num",
            str(level_num),
            "--out",
            str(output_path),
        ],
        "solution generation",
    )
    if not output_path.is_file():
        raise SubmissionError(f"planner did not create {output_path}")


def _load_actions(output_path: Path) -> Dict[str, Any]:
    try:
        with output_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubmissionError(f"generated actions file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SubmissionError("generated JSON must be a top-level object")
    if "actions" not in payload:
        raise SubmissionError("generated JSON is missing the top-level 'actions' key")
    if not isinstance(payload["actions"], list):
        raise SubmissionError("generated JSON top-level 'actions' value must be an array")
    return payload


def _validate_with_engine(
    level_path: Path, level_num: int, output_path: Path
) -> Dict[str, Any]:
    result = _run(
        [
            sys.executable,
            str(ENGINE),
            "--level",
            str(level_path),
            "--actions",
            str(output_path),
            "--level-num",
            str(level_num),
        ],
        "engine validation",
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SubmissionError(f"engine returned invalid JSON: {exc}") from exc
    invalid = report.get("invalid_actions")
    if invalid != 0:
        raise SubmissionError(f"engine reported {invalid!r} invalid actions")
    return report


def _source_files(level_path: Path) -> List[Path]:
    try:
        relative_level = level_path.relative_to(ROOT)
    except ValueError as exc:
        raise SubmissionError(
            "level file must be inside the repository so it can be packaged"
        ) from exc
    files = list(COMMON_SOURCE_FILES) + [relative_level]
    missing = [str(path) for path in files if not (ROOT / path).is_file()]
    if missing:
        raise SubmissionError("required source files are missing: " + ", ".join(missing))
    return sorted(set(files), key=lambda path: path.as_posix())


def _write_reproducible_zip(destination: Path, source_files: List[Path]) -> None:
    # ZIP timestamps cannot predate 1980.  Fixed metadata makes rebuilding the
    # source archive reproducible as well as keeping it free of host details.
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in source_files:
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / relative).read_bytes())


def make_submission(level_path: Path, level_num: int) -> Dict[str, Any]:
    level_path = level_path.resolve()
    if not level_path.is_file():
        raise SubmissionError(f"level file does not exist: {level_path}")
    source_files = _source_files(level_path)

    submission_dir = ROOT / "submissions" / f"level{level_num}"
    final_actions = submission_dir / "actions.txt"
    final_zip = submission_dir / "source.zip"

    with tempfile.TemporaryDirectory(prefix=f"level{level_num}-submission-") as temp:
        temp_dir = Path(temp)
        first = temp_dir / "actions-first.txt"
        second = temp_dir / "actions-second.txt"
        _generate(level_path, level_num, first)
        _generate(level_path, level_num, second)

        first_bytes = first.read_bytes()
        second_bytes = second.read_bytes()
        if first_bytes != second_bytes:
            raise SubmissionError(
                "determinism check failed: two complete planner runs produced "
                "different actions.txt bytes"
            )

        payload = _load_actions(first)
        report = _validate_with_engine(level_path, level_num, first)

        # Publish only after every gate has passed.  os.replace keeps each
        # individual artifact atomic if an older submission already exists.
        submission_dir.mkdir(parents=True, exist_ok=True)
        staged_actions = temp_dir / "actions.txt"
        staged_zip = temp_dir / "source.zip"
        staged_actions.write_bytes(first_bytes)
        _write_reproducible_zip(staged_zip, source_files)
        os.replace(str(staged_actions), str(final_actions))
        os.replace(str(staged_zip), str(final_zip))

    return {
        "level": level_num,
        "deterministic": True,
        "action_count": len(payload["actions"]),
        "validation": report,
        "actions_path": str(final_actions),
        "source_zip_path": str(final_zip),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate twice, verify, validate, and package one submission."
    )
    parser.add_argument("--level", required=True, type=Path)
    parser.add_argument("--level-num", required=True, type=int)
    args = parser.parse_args()

    try:
        result = make_submission(args.level, args.level_num)
    except SubmissionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
