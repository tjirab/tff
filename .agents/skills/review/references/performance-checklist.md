# Performance Review Checklist

Use this checklist during code review to identify potential bottlenecks in large-scale DAG processing:

## 1. Algorithmic Complexity & Lookups
- [ ] Model and check lookups use hash sets or dictionaries (`O(1)`), avoiding linear list scans (`O(N)`) inside nested loops.
- [ ] Duplicate CTE fingerprinting and DAG graph walks do not incur exponential or unbounded recursion.

## 2. AST Caching & Parsing
- [ ] AST parsing utilizes the persistent cache (`parse_sql_with_cache` / `get_cached_ast`).
- [ ] Cache keys incorporate parser library version, SQL dialect, and SQL content hash to guarantee cache invalidation correctness.
- [ ] Memory footprint is bounded: avoid retaining unnecessary expression copies when single traversals suffice.

## 3. Parallelism & Worker Concurrency
- [ ] CPU-bound tasks (e.g. AST parsing, duplicate CTE fingerprinting) leverage process pools (`ProcessPoolExecutor`).
- [ ] I/O-bound tasks (e.g. multi-check registry dispatch) use thread pools (`ThreadPoolExecutor`).
- [ ] Worker counts default to available CPU count capped at safe limits (e.g., `min(cpu_count, 8)`).
- [ ] Code executed inside workers is picklable and thread/process-safe (avoids shared mutable state without synchronization).

## 4. Disk & I/O
- [ ] Disk writes are buffered and minimized.
- [ ] Execution logging and cache file operations do not perform redundant stat or read calls.
