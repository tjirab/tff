# Security Review Checklist

Use this checklist during code review to identify common security concerns in transformation and CLI systems:

## 1. Secrets & Credentials
- [ ] No API keys, tokens, or passwords committed to source files or tests (except dummy values).
- [ ] Authentication tokens (e.g. `--github-token`, webhook secrets) are not written to console output, debug logs, or error traces.
- [ ] Sensitive environment variables are read safely and stripped of whitespace.

## 2. Injection & SQL/AST Manipulation
- [ ] No raw string formatting or concatenation when building SQL expressions for parsing or execution.
- [ ] Dynamic inputs to regex expressions are escaped with `re.escape()` where needed.
- [ ] Subprocess invocations (if any) use argument lists rather than `shell=True`.

## 3. Deserialization & Serialization
- [ ] Untrusted inputs are never deserialized using `pickle.loads` without integrity and provenance guarantees.
- [ ] Pickle caching (such as AST disk cache) is strictly localized to project-internal `.tff_cache/` directories with safe corrupted-cache eviction (`cache_file.unlink()`).
- [ ] YAML parsing uses safe loaders (`ruamel.yaml` safe loading or `yaml.safe_load`).

## 4. File System Operations
- [ ] Temporary files are written safely using `tempfile.NamedTemporaryFile` with atomic renaming (`replace`).
- [ ] Directory traversal risks are prevented by validating that resolved paths stay within the expected project root.
- [ ] File deletions (e.g. cache cleanup, log rotation) restrict targets strictly to expected extensions and directories.
