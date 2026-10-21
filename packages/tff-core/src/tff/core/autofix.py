"""Auto-fixing engine for tff lint violations.

Curated to safe, non-destructive, high-confidence mutations only:
synchronizing internal model declarations with file stems.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tff.core.adapter import PipelineAdapter
    from tff.core.config import TffConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


def atomic_write(
    path: Path | str,
    content: str,
    encoding: str = "utf-8",
) -> None:
    """Atomically write text content to a destination file.

    Writes to a temporary file in the destination's parent directory and performs
    an atomic rename/replace to prevent file corruption during interruptions.
    """
    target = Path(path).resolve()
    if target.is_dir():
        raise IsADirectoryError(f"[Errno 21] Is a directory: '{target}'")
    if target.exists() and not os.access(target, os.W_OK):
        raise PermissionError(f"[Errno 13] Permission denied: '{target}'")

    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            encoding=encoding,
            delete=False,
        ) as tf:
            tf.write(content)
            tf.flush()
            try:
                os.fsync(tf.fileno())
            except OSError:
                pass
            temp_path = Path(tf.name)

        if target.exists():
            try:
                shutil.copymode(target, temp_path)
            except OSError:
                pass
        else:
            try:
                current_umask = os.umask(0)
                os.umask(current_umask)
                os.chmod(temp_path, 0o666 & ~current_umask)
            except OSError:
                pass

        temp_path.replace(target)
    except Exception:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


atomic_write_text = atomic_write


def _find_matching_brace(text: str, open_brace_idx: int) -> int:
    """Find the index of the matching closing brace '}' for the open brace at open_brace_idx."""
    if open_brace_idx < 0 or open_brace_idx >= len(text) or text[open_brace_idx] != "{":
        return -1
    depth = 0
    in_quote = None
    i = open_brace_idx
    length = len(text)
    while i < length:
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < length:
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'", "`"):
            in_quote = ch
        elif ch == "/" and i + 1 < length and text[i + 1] == "/":
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        elif ch == "/" and i + 1 < length and text[i + 1] == "*":
            end_c = text.find("*/", i + 2)
            if end_c == -1:
                break
            i = end_c + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_matching_paren(text: str, open_paren_idx: int) -> int:
    """Find the index of the matching closing parenthesis ')' for the open parenthesis at open_paren_idx."""
    if open_paren_idx < 0 or open_paren_idx >= len(text) or text[open_paren_idx] != "(":
        return -1
    depth = 0
    in_quote = None
    i = open_paren_idx
    length = len(text)
    while i < length:
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < length:
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'", "`"):
            in_quote = ch
        elif ch == "-" and i + 1 < length and text[i + 1] == "-":
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        elif ch == "/" and i + 1 < length and text[i + 1] == "*":
            end_c = text.find("*/", i + 2)
            if end_c == -1:
                break
            i = end_c + 2
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def sync_sqlmesh_model_name(sql: str, new_name_stem: str) -> str:
    """Update the model identifier in a SQLMesh MODEL(...) block to match new_name_stem.

    Preserves schema qualification (e.g. `schema.model` -> `schema.<new_name_stem>`)
    and quotes (e.g. `"schema"."model"` -> `"schema"."<new_name_stem>"`).
    """
    model_match = re.search(r"\bMODEL\s*\(", sql, re.IGNORECASE)
    if not model_match:
        return sql

    open_paren = model_match.end() - 1
    close_paren = _find_matching_paren(sql, open_paren)
    if close_paren == -1:
        return sql

    block_content = sql[open_paren + 1 : close_paren]

    name_match = re.search(
        r"(\bname(?:\s*:\s*|\s+))([^\s,);]+)",
        block_content,
        re.IGNORECASE,
    )
    if name_match:
        full_ident = name_match.group(2)
        parts = full_ident.split(".")
        last_part = parts[-1]

        quote = ""
        for q in ('"', "'", "`"):
            if last_part.startswith(q) and last_part.endswith(q) and len(last_part) >= 2:
                quote = q
                break

        new_last_part = f"{quote}{new_name_stem}{quote}"
        new_parts = parts[:-1] + [new_last_part]
        new_ident = ".".join(new_parts)

        if new_ident == full_ident:
            return sql

        new_block_content = (
            block_content[: name_match.start(2)]
            + new_ident
            + block_content[name_match.end(2) :]
        )
        return sql[: open_paren + 1] + new_block_content + sql[close_paren :]
    else:
        indent = "  "
        new_block_content = f"\n{indent}name {new_name_stem}," + block_content
        return sql[: open_paren + 1] + new_block_content + sql[close_paren :]


def sync_dataform_model_name(content: str, new_name_stem: str) -> str:
    """Update the name property inside Dataform config { ... } to match new_name_stem."""
    match = re.search(r"^\s*config\s*\{", content, re.MULTILINE | re.IGNORECASE)
    if not match:
        match = re.search(r"\bconfig\s*\{", content, re.IGNORECASE)
    if not match:
        return content

    brace_start = match.end() - 1
    brace_end = _find_matching_brace(content, brace_start)
    if brace_end == -1:
        return content

    config_str = content[brace_start : brace_end + 1]

    name_match = re.search(r'(\bname\s*:\s*)(["\']?)([\w.-]+)\2', config_str)
    if name_match:
        prefix = name_match.group(1)
        quote = name_match.group(2) or '"'
        old_val = name_match.group(3)
        if old_val == new_name_stem:
            return content
        replacement = f"{prefix}{quote}{new_name_stem}{quote}"
        new_config = (
            config_str[: name_match.start()]
            + replacement
            + config_str[name_match.end() :]
        )
        return content[:brace_start] + new_config + content[brace_end + 1 :]

    return content


def apply_autofixes(
    project_root: Path | Sequence[Path],
    provider: str | PipelineAdapter,
    findings: list[LintFinding],
    models: dict[str, ModelRepresentation],
    config: TffConfig | None = None,
) -> list[str]:
    """Identify auto-fixable violations from findings and apply modifications to source files."""
    from tff.core.adapter import get_adapter, normalize_project_roots

    if isinstance(provider, str):
        adapter = get_adapter(provider)
    else:
        adapter = provider

    roots = normalize_project_roots(project_root)

    # Group findings by file path
    grouped = defaultdict(list)
    for f in findings:
        if f.path:
            p = Path(f.path)
            if p.is_absolute():
                abs_path = p.resolve()
            else:
                abs_path = (roots[0] / f.path).resolve()
                for r in roots:
                    cand = (r / f.path).resolve()
                    if cand.exists():
                        abs_path = cand
                        break
            grouped[abs_path].append(f)

    applied_logs = []

    for abs_path, file_findings in grouped.items():
        if not abs_path.exists():
            continue

        # Fix filename and model name synchronization (filename_equals_modelname)
        name_sync_findings = [
            f
            for f in file_findings
            if f.check in ("filenameequalsmodelname", "filename_equals_modelname")
        ]
        if name_sync_findings and abs_path.suffix in (".sql", ".sqlx"):
            provider_name = getattr(adapter, "provider_name", str(provider)).lower()
            is_sqlmesh = provider_name == "sqlmesh"
            is_dataform = provider_name == "dataform" or abs_path.suffix == ".sqlx"

            try:
                content = abs_path.read_text(encoding="utf-8")
                if is_dataform:
                    new_content = sync_dataform_model_name(content, abs_path.stem)
                elif is_sqlmesh or re.search(r"\bMODEL\s*\(", content, re.IGNORECASE):
                    new_content = sync_sqlmesh_model_name(content, abs_path.stem)
                else:
                    new_content = content

                if new_content != content:
                    atomic_write(abs_path, new_content)
                    applied_logs.append(
                        f"Synchronized model name to '{abs_path.stem}' in {abs_path.name}"
                    )
            except Exception as e:
                applied_logs.append(
                    f"Failed to synchronize model name in {abs_path.name}: {e}"
                )

    return applied_logs
