"""Structured exception hierarchy and OS error translation utilities for tff-core."""

from __future__ import annotations

from contextlib import contextmanager
import errno
from pathlib import Path
from typing import Any, Generator


class TffError(Exception):
    """Base domain exception for all tff errors.

    Attributes:
        message: Descriptive explanation of the error.
        hint: Optional actionable remediation hint for the user.
        details: Contextual metadata dictionary (e.g. paths, model names, errnos).
        original_error: The underlying chained or wrapped exception if available.
    """

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details: dict[str, Any] = details.copy() if details is not None else {}
        self.original_error = original_error

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\nHint: {self.hint}"
        return self.message


class TffFileError(TffError, OSError):
    """Exception raised for file access and I/O issues.

    Attributes:
        path: Target file or directory path.
        operation: File operation attempted (e.g. 'read', 'write', 'open').
    """

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        *,
        path: str | Path | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        det = details.copy() if details is not None else {}
        if path is not None:
            det.setdefault("path", str(path))
        if operation is not None:
            det.setdefault("operation", operation)
        super().__init__(
            message,
            hint=hint,
            details=det,
            original_error=original_error,
        )
        self.path: Path | None = Path(path) if path is not None else None
        self.operation: str | None = operation


class TffModelError(TffError):
    """Exception raised for model resolution, loading, or reading errors.

    Attributes:
        model_name: Name of the model.
        path: Resolved path to the model file if applicable.
    """

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        *,
        model_name: str | None = None,
        path: str | Path | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        det = details.copy() if details is not None else {}
        if model_name is not None:
            det.setdefault("model_name", model_name)
        if path is not None:
            det.setdefault("path", str(path))
        super().__init__(
            message,
            hint=hint,
            details=det,
            original_error=original_error,
        )
        self.model_name: str | None = model_name
        self.path: Path | None = Path(path) if path is not None else None


class TffConfigError(TffError, ValueError):
    """Exception raised for configuration file parsing, resolution, and schema validation errors.

    Attributes:
        path: Path to the configuration file if applicable.
    """

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        *,
        path: str | Path | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        det = details.copy() if details is not None else {}
        if path is not None:
            det.setdefault("path", str(path))
        super().__init__(
            message,
            hint=hint,
            details=det,
            original_error=original_error,
        )
        self.path: Path | None = Path(path) if path is not None else None


class TffManifestError(TffError, OSError):
    """Exception raised for provider manifest loading and parsing failures.

    Attributes:
        provider: Provider identifier (e.g. 'dbt', 'dataform', 'sqlmesh').
        path: Resolved path to the manifest file if applicable.
    """

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        *,
        provider: str | None = None,
        path: str | Path | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        det = details.copy() if details is not None else {}
        if provider is not None:
            det.setdefault("provider", provider)
        if path is not None:
            det.setdefault("path", str(path))
        super().__init__(
            message,
            hint=hint,
            details=det,
            original_error=original_error,
        )
        self.provider: str | None = provider
        self.path: Path | None = Path(path) if path is not None else None


class TffManifestNotFoundError(TffManifestError, FileNotFoundError):
    """Exception raised when a required provider manifest file cannot be found."""
    pass


def normalize_os_error(
    exc: Exception,
    *,
    path: str | Path | None = None,
    operation: str = "read",
    model_name: str | None = None,
    expected_type: str = "file",
    provider: str | None = None,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> TffError:
    """Normalize low-level OS/POSIX errors into human-friendly domain exceptions.

    Maps errnos such as EISDIR, ENOENT, EACCES, and ENOTDIR to descriptive messages
    and actionable remediation hints.

    Args:
        exc: The caught low-level exception or OS error.
        path: Path to the target file or directory.
        operation: Operation being attempted (e.g. 'read', 'write', 'open').
        model_name: Optional model identifier for model-specific context.
        expected_type: Description of expected resource (e.g. 'file', 'SQL file', 'manifest file').
        provider: Optional provider name (e.g. 'dbt', 'dataform', 'sqlmesh').
        hint: Explicit hint overriding automatic hint generation.
        details: Additional contextual dictionary attributes.

    Returns:
        A domain-specific TffError subclass (TffManifestError, TffModelError, or TffFileError).
    """
    if isinstance(exc, TffError):
        return exc

    err_no = getattr(exc, "errno", None)
    target_path = path if path is not None else getattr(exc, "filename", None)
    path_str = str(target_path) if target_path is not None else "<unknown path>"

    det: dict[str, Any] = details.copy() if details is not None else {}
    if err_no is not None:
        det.setdefault("errno", err_no)
    if target_path is not None:
        det.setdefault("path", str(target_path))
    det.setdefault("operation", operation)
    det.setdefault("expected_type", expected_type)
    det.setdefault("original_error", str(exc))
    if model_name is not None:
        det.setdefault("model_name", model_name)
    if provider is not None:
        det.setdefault("provider", provider)

    default_hint: str
    if err_no == errno.EISDIR or isinstance(exc, IsADirectoryError):
        message = f"Expected a {expected_type}, but encountered a directory: '{path_str}'"
        default_hint = f"Ensure the path '{path_str}' points to a valid file, not a directory."
    elif err_no == errno.ENOENT or isinstance(exc, FileNotFoundError):
        message = f"No such {expected_type}: '{path_str}'"
        default_hint = f"Verify that the file exists at '{path_str}' and the path is spelled correctly."
    elif err_no in (errno.EACCES, errno.EPERM) or isinstance(exc, PermissionError):
        message = f"Permission denied while attempting to {operation} {expected_type}: '{path_str}'"
        default_hint = f"Check filesystem permissions to ensure '{path_str}' is accessible."
    elif err_no == errno.ENOTDIR or isinstance(exc, NotADirectoryError):
        message = f"A component of the path prefix is not a directory: '{path_str}'"
        default_hint = f"Check the directory structure leading to '{path_str}'."
    elif err_no in (errno.EMFILE, errno.ENFILE):
        message = f"Too many open files while attempting to {operation} {expected_type}: '{path_str}'"
        default_hint = "Consider reducing concurrency (e.g. workers configuration) or increasing system ulimit."
    else:
        message = f"Failed to {operation} {expected_type} '{path_str}': {exc}"
        default_hint = "Check system logs and filesystem status."

    effective_hint = hint if hint is not None else default_hint

    if provider is not None:
        if err_no == errno.ENOENT or isinstance(exc, FileNotFoundError):
            return TffManifestNotFoundError(
                message,
                hint=effective_hint,
                provider=provider,
                path=target_path,
                details=det,
                original_error=exc,
            )
        return TffManifestError(
            message,
            hint=effective_hint,
            provider=provider,
            path=target_path,
            details=det,
            original_error=exc,
        )

    if model_name is not None:
        return TffModelError(
            message,
            hint=effective_hint,
            model_name=model_name,
            path=target_path,
            details=det,
            original_error=exc,
        )

    return TffFileError(
        message,
        hint=effective_hint,
        path=target_path,
        operation=operation,
        details=det,
        original_error=exc,
    )


# Alias for normalize_os_error
translate_os_error = normalize_os_error


@contextmanager
def handle_os_errors(
    *,
    path: str | Path | None = None,
    operation: str = "read",
    model_name: str | None = None,
    expected_type: str = "file",
    provider: str | None = None,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> Generator[None, None, None]:
    """Context manager translating low-level OSErrors into structured TffErrors.

    Example:
        with handle_os_errors(path=file_path, operation="read", expected_type="SQL file"):
            content = Path(file_path).read_text(encoding="utf-8")
    """
    try:
        yield
    except OSError as exc:
        raise normalize_os_error(
            exc,
            path=path,
            operation=operation,
            model_name=model_name,
            expected_type=expected_type,
            provider=provider,
            hint=hint,
            details=details,
        ) from exc


__all__ = [
    "TffError",
    "TffFileError",
    "TffModelError",
    "TffConfigError",
    "TffManifestError",
    "TffManifestNotFoundError",
    "normalize_os_error",
    "translate_os_error",
    "handle_os_errors",
]
