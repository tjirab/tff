# ADR-0002: Parallel AST Caching Strategy

- **Status**: Accepted
- **Deciders**: `tff` Core Maintainers
- **Date**: 2026-10-10

---

## Context and Problem Statement

`tff` inspects entire data warehouse projects containing hundreds or thousands of SQL models. Parsing complex SQL queries into Abstract Syntax Trees (ASTs) via `sqlglot` is computationally intensive, often consuming 80-90% of total CI execution time if performed sequentially on every commit.

Furthermore, in continuous integration (CI) workflows, typical pull requests only modify a small fraction of models (e.g. 1-10 models out of 2,000). Reparsing unchanged SQL queries is redundant and degrades developer feedback loop speed.

How should `tff` architect AST parsing and caching to optimize throughput and response times in both interactive development and CI environments?

---

## Decision Drivers

- **Execution Speed**: Sub-second execution on incremental runs; minimized turnaround time in CI and pre-commit hooks.
- **Multiprocessing Scalability**: Efficient multi-core saturation without process contention or inter-process communication (IPC) serialization bottlenecks.
- **Cache Invalidation Correctness**: Zero false cache hits across dialect changes, SQLGlot library updates, or macro modifications.
- **Portability**: Cache artifacts must operate cleanly across Linux, macOS, and containerized CI runners.

---

## Considered Options

1. **Two-Tier Cache (L1 In-Memory + L2 Content-Addressable Disk Cache) with Process Worker Pool**:
   - In-memory dictionary for fast single-process re-evaluation.
   - Content-addressable disk storage keyed on SHA-256 hashes of `(sqlglot_version, dialect, normalized_sql)`.
   - Multi-process worker pool (`ProcessPoolExecutor`) for parallel parsing of uncached models.
2. **Sequential In-Memory Caching Only**:
   - Cache ASTs in-memory during single process lifecycle; discard upon exit.
3. **Database-backed Cache (SQLite / DuckDB)**:
   - Persist parsed ASTs or serialized graphs in a local SQLite/DuckDB database file.

---

## Decision Outcome

Chosen option: **Option 1: Two-Tier Cache with Process Worker Pool**.

### Positive Consequences

- **High Speed**: Cache hits bypass the SQLGlot lexer/parser entirely, deserializing pre-parsed AST trees via pickle or fast retrieval.
- **Deterministic Invalidation**: The SHA-256 cache key incorporates the exact `SQLGLOT_VERSION`, SQL dialect, and normalized query string. If any of these factors change, the cache misses automatically without stale artifacts.
- **Parallel Saturation**: AST parsing tasks are distributed across worker processes (configured via `workers`, `TFF_WORKERS`, or auto-capped to CPU cores), saturating multi-core machines.
- **CI Caching Support**: The `.tff_cache/ast` directory can be preserved across CI jobs via standard cache actions (e.g. `actions/cache`).

### Negative Consequences & Trade-offs

- Disk footprint: Storing pickle files for large repositories consumes disk space (mitigated by placing in `.tff_cache/` and enabling directory sharding by initial hash prefix `xx/yyyy...`).
- Serialization cost: Pickle deserialization incurs minor overhead, though it remains an order of magnitude faster than full lexical AST parsing.

---

## Pros and Cons of Options

### Option 1: Two-Tier Cache + Process Worker Pool

- Positive: Dramatic speedups on warm runs (often >10x acceleration); resilient against process crashes; trivial CI caching.
- Positive: L1 memory cache eliminates redundant parsing during multiple rule evaluations within the same process.
- Negative: Disk I/O management and cache folder ignore handling (`.gitignore`).

### Option 2: Sequential In-Memory Caching Only

- Positive: Zero disk artifact management.
- Negative: Does not persist across CLI invocations; warm CI runs gain zero benefit; sequential processing scales poorly on large projects.

### Option 3: Database-backed Cache (SQLite / DuckDB)

- Positive: Single file storage.
- Negative: Concurrent worker write lock contention issues in multiprocess setups; unnecessary query engine overhead for pure key-value AST blob storage.

---

## Technical Details & Architecture Notes

- Cache keys are generated via SHA-256:
  `hashlib.sha256(f"{SQLGLOT_VERSION}:{dialect}:{normalized_sql}".encode("utf-8")).hexdigest()`
- Storage path convention:
  `.tff_cache/ast/<hash[:2]>/<hash[2:]>.ast`
- Sharding by the first two characters prevents filesystem degradation with tens of thousands of cached files.
- Controlled via `is_cache_enabled()` and configuration flags: `cache_ast: true`, `cache_dir: ".tff_cache"`, or `TFF_NO_CACHE=1`.
