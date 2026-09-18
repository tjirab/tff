# Exceptions API Reference

tff provides a centralized domain exception hierarchy and OS error translation layer in `tff.core.exceptions`. This ensures that filesystem errors, model resolution failures, and configuration issues surface with clear domain context (such as model name, file path, and provider) along with actionable remediation hints.

---

## Architecture & Hierarchy

```text
TffError (Exception)
├── TffFileError (TffError, OSError)
├── TffModelError (TffError)
├── TffConfigError (TffError, ValueError)
└── TffManifestError (TffError, OSError)
    └── TffManifestNotFoundError (TffManifestError, FileNotFoundError)
```

Every `TffError` carries:
* **`message`**: A clear, human-friendly explanation of what failed.
* **`hint`**: An actionable suggestion explaining how to resolve or prevent the error.
* **`details`**: A structured dictionary containing contextual metadata (e.g. `path`, `operation`, `model_name`, `provider`, `errno`).
* **`original_error`**: The underlying wrapped or chained exception, if applicable.

---

## OS Error Normalization

Low-level POSIX errors (`errno.EISDIR`, `errno.ENOENT`, `errno.EACCES`, `errno.ENOTDIR`, `errno.EMFILE`) are automatically normalized into descriptive domain exceptions by `normalize_os_error` (aliased as `translate_os_error`).

For example, an `EISDIR` encountered when opening a model SQL file produces:
```text
Expected a SQL file, but encountered a directory: '/path/to/model'
Hint: Ensure the path '/path/to/model' points to a valid file, not a directory.
```

---

## Module Reference

::: tff.core.exceptions
    options:
      show_root_heading: true
      show_source: true
      heading_level: 2
