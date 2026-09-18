# Changelog

## [0.20.0](https://github.com/tjirab/tff/compare/tff-core-v0.19.0...tff-core-v0.20.0) (2026-09-18)


### Features

* **cli:** human-readable error diagnostics and top-level exception boundary ([#247](https://github.com/tjirab/tff/issues/247)) ([#251](https://github.com/tjirab/tff/issues/251)) ([b206206](https://github.com/tjirab/tff/commit/b206206b5259b7ba6c559f124b8753bd00a6e83b))
* **core:** introduce structured exception hierarchy and OS error translator ([#246](https://github.com/tjirab/tff/issues/246)) ([#249](https://github.com/tjirab/tff/issues/249)) ([64c992c](https://github.com/tjirab/tff/commit/64c992c80098749e0277e0ea3dd4d91914842a0e))
* **core:** isolate per-model rule execution errors with contextual diagnostics ([#248](https://github.com/tjirab/tff/issues/248)) ([#254](https://github.com/tjirab/tff/issues/254)) ([c423e09](https://github.com/tjirab/tff/commit/c423e09322b3dd5e85efedc85a5fed1bcc7e0999))


### Bug Fixes

* **dbt:** handle empty original_file_path and avoid EISDIR in environment_agnostic_references ([#236](https://github.com/tjirab/tff/issues/236)) ([0e94c31](https://github.com/tjirab/tff/commit/0e94c3176ff818ad53af1a3f06fc4b6c2791e54f))


### Performance Improvements

* **parallel:** optimize executor task chunking for large model repositories ([#256](https://github.com/tjirab/tff/issues/256)) ([#258](https://github.com/tjirab/tff/issues/258)) ([68b8b0d](https://github.com/tjirab/tff/commit/68b8b0d95e0ea2beff2c2b008b8ea6c38b48cf30))

## [0.19.0](https://github.com/tjirab/tff/compare/tff-core-v0.18.0...tff-core-v0.19.0) (2026-09-17)


### Features

* **cli:** support multi-project flags (-p / --project) in docs and stats commands ([#225](https://github.com/tjirab/tff/issues/225)) ([#229](https://github.com/tjirab/tff/issues/229)) ([d00577a](https://github.com/tjirab/tff/commit/d00577af7c4a006610c609a60bfb901385398845))
* **docs:** add VHS terminal demo GIFs and check CLI alias ([#232](https://github.com/tjirab/tff/issues/232)) ([8828dd7](https://github.com/tjirab/tff/commit/8828dd757a6b9447ed4e7a5866bbcafd5e00c9a9))
* **sqlmesh:** support multi-repo projects and repeatable CLI project flags ([#223](https://github.com/tjirab/tff/issues/223)) ([29dc5ed](https://github.com/tjirab/tff/commit/29dc5ed4dec9b569ba693ffd587f0fa3745ba330))


### Performance Improvements

* **core:** deduplicate project roots in normalize_project_roots ([#228](https://github.com/tjirab/tff/issues/228)) ([3b21faf](https://github.com/tjirab/tff/commit/3b21faf28afbbd6d470e1e01c271eb5b957a3bbf))

## [0.18.0](https://github.com/tjirab/tff/compare/tff-core-v0.17.0...tff-core-v0.18.0) (2026-09-17)


### Features

* **branding:** refactor TFF to lowercase tff and update info logo ([#219](https://github.com/tjirab/tff/issues/219)) ([ce2f975](https://github.com/tjirab/tff/commit/ce2f975857f6dfec81769aa9abf108acc96b3262))

## [0.17.0](https://github.com/tjirab/tff/compare/tff-core-v0.16.1...tff-core-v0.17.0) (2026-09-16)


### Features

* **autofix:** [1/5] Close Dataform metadata auto-fix parity gap ([#212](https://github.com/tjirab/tff/issues/212)) ([2a29f84](https://github.com/tjirab/tff/commit/2a29f84afbb270ee80c4b45ca9582e9a79bfbb86))
* **autofix:** refactor nested subqueries in final SELECT to named CTEs ([#216](https://github.com/tjirab/tff/issues/216)) ([2da4f59](https://github.com/tjirab/tff/commit/2da4f59fd600f561dc52f5a6935709675ae13d43))

## [0.16.1](https://github.com/tjirab/tff/compare/tff-core-v0.16.0...tff-core-v0.16.1) (2026-09-15)


### Bug Fixes

* **core:** resolve get_ast_cache_dir to ast subdirectory when directory exists ([#189](https://github.com/tjirab/tff/issues/189)) ([#209](https://github.com/tjirab/tff/issues/209)) ([c3ded50](https://github.com/tjirab/tff/commit/c3ded5034fe9d4922967edbdd146ab78b0d8855d))
* **core:** respect TFF_NO_CACHE in parse_sql_with_cache ([#188](https://github.com/tjirab/tff/issues/188)) ([#207](https://github.com/tjirab/tff/issues/207)) ([78d9410](https://github.com/tjirab/tff/commit/78d941077a035aceacee3dfb1020c8c1d625263e))
* **cov:** preserve literals containing '@' and skip SQLMesh macro cleanup in dbt ([#175](https://github.com/tjirab/tff/issues/175)) ([#204](https://github.com/tjirab/tff/issues/204)) ([b4934ca](https://github.com/tjirab/tff/commit/b4934ca6140dfd4ebb41fd8f479ffec39f7a8baa))

## [0.16.0](https://github.com/tjirab/tff/compare/tff-core-v0.15.1...tff-core-v0.16.0) (2026-09-15)


### Features

* **rules:** deprecate and remove warn_only in sql_complexity ([#202](https://github.com/tjirab/tff/issues/202)) ([779e574](https://github.com/tjirab/tff/commit/779e57432d120b0a863529df400f7a676a10d9fa))

## [0.15.1](https://github.com/tjirab/tff/compare/tff-core-v0.15.0...tff-core-v0.15.1) (2026-09-15)


### Bug Fixes

* **rules:** resolve warning vs error severity mismatch in sql_complexity ([#198](https://github.com/tjirab/tff/issues/198)) ([f6f20f4](https://github.com/tjirab/tff/commit/f6f20f44e4cde39e67a027feb35d4d52bd50ca76))

## [0.15.0](https://github.com/tjirab/tff/compare/tff-core-v0.14.0...tff-core-v0.15.0) (2026-09-13)


### Features

* **cli:** add --debug flag and verbose logging for under-the-hood inspection ([#191](https://github.com/tjirab/tff/issues/191)) ([8ab1004](https://github.com/tjirab/tff/commit/8ab100474364e86ff13302b9c7e0aa22c0cd71ec))


### Performance Improvements

* **core:** parallelize AST traversal and duplicate CTE fingerprinting ([#161](https://github.com/tjirab/tff/issues/161)) ([#187](https://github.com/tjirab/tff/issues/187)) ([83c5ab6](https://github.com/tjirab/tff/commit/83c5ab6924621747d22644b2b3507aba0d2c80f7))

## [0.14.0](https://github.com/tjirab/tff/compare/tff-core-v0.13.0...tff-core-v0.14.0) (2026-09-13)


### Features

* **plugins:** support custom fitness rules and third-party adapters via entry points ([#160](https://github.com/tjirab/tff/issues/160)) ([#185](https://github.com/tjirab/tff/issues/185)) ([56304bf](https://github.com/tjirab/tff/commit/56304bf0b3043e62e10b02e25d401c780e785019))

## [0.13.0](https://github.com/tjirab/tff/compare/tff-core-v0.12.1...tff-core-v0.13.0) (2026-09-11)


### Features

* **ci:** create official GitHub Action for GitHub Marketplace ([#165](https://github.com/tjirab/tff/issues/165)) ([#179](https://github.com/tjirab/tff/issues/179)) ([450b966](https://github.com/tjirab/tff/commit/450b966d9388fa412be7813878e96d62978d6a42))
* **cli:** support SARIF, JUnit XML, and GitHub Actions annotations in tff lint ([#173](https://github.com/tjirab/tff/issues/173)) ([3f4aaef](https://github.com/tjirab/tff/commit/3f4aaef93b4e51c9f21054530f46849c954656fa))
* **health:** configurable check weights and failure penalties for health scoring ([#159](https://github.com/tjirab/tff/issues/159)) ([#176](https://github.com/tjirab/tff/issues/176)) ([613613e](https://github.com/tjirab/tff/commit/613613e2c1cb6ee2677007ef9db244f7995ddae1))


### Documentation

* harmonize documentation, CLI flags, and CI example configs ([#155](https://github.com/tjirab/tff/issues/155)) ([#177](https://github.com/tjirab/tff/issues/177)) ([92f8b54](https://github.com/tjirab/tff/commit/92f8b54aa9b6d433e1c9e7173b023e4aff93bb11))

## [0.12.1](https://github.com/tjirab/tff/compare/tff-core-v0.12.0...tff-core-v0.12.1) (2026-09-11)


### Bug Fixes

* **cov:** exclude structural and positional SQL literals from connascence of value check ([#171](https://github.com/tjirab/tff/issues/171)) ([31ddd72](https://github.com/tjirab/tff/commit/31ddd72d3cb662a385422d09b2789efbc9e21ec8))

## [0.12.0](https://github.com/tjirab/tff/compare/tff-core-v0.11.0...tff-core-v0.12.0) (2026-09-10)


### Features

* **ci:** add pre-commit hook support (.pre-commit-hooks.yaml) ([#170](https://github.com/tjirab/tff/issues/170)) ([16a2a73](https://github.com/tjirab/tff/commit/16a2a7364b7d2a5ded8ec2b6eaa93e9011fcb2fe))
* **core:** zero-config default execution for instant onboarding ([#163](https://github.com/tjirab/tff/issues/163)) ([#168](https://github.com/tjirab/tff/issues/168)) ([e141bb2](https://github.com/tjirab/tff/commit/e141bb2eb88e85d5cfb1574e3fbafbf7b99e5f12))

## [0.11.0](https://github.com/tjirab/tff/compare/tff-core-v0.10.0...tff-core-v0.11.0) (2026-09-09)


### Features

* **registry:** unified CheckRegistry and granular rule execution (tff[#146](https://github.com/tjirab/tff/issues/146)) ([#152](https://github.com/tjirab/tff/issues/152)) ([d690825](https://github.com/tjirab/tff/commit/d690825d098ebc79c730572f491a6d0042569b2d))


### Bug Fixes

* **core:** resolve correctness bugs, false positives, and metric distortions (tff[#144](https://github.com/tjirab/tff/issues/144)) ([#148](https://github.com/tjirab/tff/issues/148)) ([56b75af](https://github.com/tjirab/tff/commit/56b75affc8328e3843db14d01681f09449cd9492))

## [0.10.0](https://github.com/tjirab/tff/compare/tff-core-v0.9.0...tff-core-v0.10.0) (2026-09-06)


### Features

* **dataform:** support Google Cloud Dataform projects (tff[#137](https://github.com/tjirab/tff/issues/137)) ([#142](https://github.com/tjirab/tff/issues/142)) ([b73428f](https://github.com/tjirab/tff/commit/b73428fcb19e16a300bb7de1194fa1332fd93e66))

## [0.9.0](https://github.com/tjirab/tff/compare/tff-core-v0.8.0...tff-core-v0.9.0) (2026-08-31)


### Features

* **cli:** add --fix flag to tff lint for auto-fixing simple violations ([#136](https://github.com/tjirab/tff/issues/136)) ([2289885](https://github.com/tjirab/tff/commit/22898858cf5420bb8879fc9ac26694f519ae6281))
* **governance:** HTML dashboard and history reporting (tff[#125](https://github.com/tjirab/tff/issues/125)) ([#141](https://github.com/tjirab/tff/issues/141)) ([f3c16e2](https://github.com/tjirab/tff/commit/f3c16e28a06914f3a89feb03568ffd14ca2047af))

## [0.8.0](https://github.com/tjirab/tff/compare/tff-core-v0.7.0...tff-core-v0.8.0) (2026-08-27)


### Features

* **checks:** add connascence of value (CoV) check ([#134](https://github.com/tjirab/tff/issues/134)) ([6766224](https://github.com/tjirab/tff/commit/6766224e856f110a0b38026d518332f1e6e55325))
* **cli:** default to help command and show tff version ([#118](https://github.com/tjirab/tff/issues/118)) ([246937c](https://github.com/tjirab/tff/commit/246937cf796a349d3d46190a699d9e5f183acc59))
* metadata and tag-driven layer boundaries and exclusions ([#121](https://github.com/tjirab/tff/issues/121)) ([#131](https://github.com/tjirab/tff/issues/131)) ([aa30958](https://github.com/tjirab/tff/commit/aa30958248ff85d71e43084b64a298547c5eb061))
* **perf:** implement AST caching on ModelRepresentation ([#120](https://github.com/tjirab/tff/issues/120)) ([#128](https://github.com/tjirab/tff/issues/128)) ([63ad787](https://github.com/tjirab/tff/commit/63ad7870b2078de8c611fa213ccf66e6f562e3cb))


### Bug Fixes

* **robustness:** improve fallback Jinja parsing in local SQLGlot checks ([#123](https://github.com/tjirab/tff/issues/123)) ([#130](https://github.com/tjirab/tff/issues/130)) ([f422623](https://github.com/tjirab/tff/commit/f4226235964654e16d650ff3dc817097b6e9fa54))

## [0.7.0](https://github.com/tjirab/tff/compare/tff-core-v0.6.0...tff-core-v0.7.0) (2026-08-11)


### Features

* **dbt:** Assert dbt metadata check coverage ([#112](https://github.com/tjirab/tff/issues/112)) ([2f9d4b7](https://github.com/tjirab/tff/commit/2f9d4b75494bb82d96e1068bcbea1ce84bcd40e4))
* support nested layer and domain resolution ([#108](https://github.com/tjirab/tff/issues/108)) ([#109](https://github.com/tjirab/tff/issues/109)) ([8cdb7be](https://github.com/tjirab/tff/commit/8cdb7be86b0abe58bd092d866d3cf5d3a2112c83))

## [0.6.0](https://github.com/tjirab/tff/compare/tff-core-v0.5.0...tff-core-v0.6.0) (2026-07-27)


### Features

* consolidate packages into tff-core with extras ([#98](https://github.com/tjirab/tff/issues/98)) ([1c1cfd9](https://github.com/tjirab/tff/commit/1c1cfd9d0637876518a0ff59c6760ec7ceb909db))

## [0.5.0](https://github.com/tjirab/tff/compare/tff-core-v0.4.0...tff-core-v0.5.0) (2026-07-04)


### Features

* `tff health` domain filtering and grouping ([#90](https://github.com/tjirab/tff/issues/90)) ([0fc2441](https://github.com/tjirab/tff/commit/0fc2441c0070fc84538007c4801a3fd5b90f83c3))
* add JSON CLI output and local execution logging with 60-day cleanup ([#92](https://github.com/tjirab/tff/issues/92)) ([0010e8e](https://github.com/tjirab/tff/commit/0010e8ea1727e6e23c006d74424d4b8403e52a47))
* add tff stats command with ASCII trend graphs and daily history summaries ([#93](https://github.com/tjirab/tff/issues/93)) ([f6d2ee1](https://github.com/tjirab/tff/commit/f6d2ee1328c690dec6fd379cd31846edb00f8864))

## [0.4.0](https://github.com/tjirab/tff/compare/tff-core-v0.3.0...tff-core-v0.4.0) (2026-06-30)


### Features

* add duplicate CTE fingerprinting linter check (Connascence of Algorithm) ([#83](https://github.com/tjirab/tff/issues/83)) ([96bdb40](https://github.com/tjirab/tff/commit/96bdb406c4cd3249886a25afb0adbb90e0d158dc))
* default tff lint grouping to model ([#71](https://github.com/tjirab/tff/issues/71)) ([#72](https://github.com/tjirab/tff/issues/72)) ([f980aa3](https://github.com/tjirab/tff/commit/f980aa3193fc3e9c317a78a5e7793d1a0fd313f6))


### Bug Fixes

* resolve [dim]Disabled[/dim] rich text formatting in health report ([#75](https://github.com/tjirab/tff/issues/75)) ([a63be79](https://github.com/tjirab/tff/commit/a63be79f26fcc13e48924c911f593e1c0fe83fe8))

## [0.3.0](https://github.com/tjirab/tff/compare/tff-core-v0.2.3...tff-core-v0.3.0) (2026-06-29)


### Features

* add tff info command and improve CLI help coverage ([#64](https://github.com/tjirab/tff/issues/64)) ([f8e78d7](https://github.com/tjirab/tff/commit/f8e78d7397a701c528dee4ae00bef5f6e65fd34c))
* improve TFF CLI design system, headers, and alignments ([#69](https://github.com/tjirab/tff/issues/69)) ([a2ecef1](https://github.com/tjirab/tff/commit/a2ecef1ef379eb8a33f3a1636d9f2fa4d5d806be))


### Bug Fixes

* resolve target project adapter resolution and cross-environment imports ([#66](https://github.com/tjirab/tff/issues/66)) ([6b6a6c2](https://github.com/tjirab/tff/commit/6b6a6c22ffaf3137e106b17cd442cec1efe36bd2))

## [0.2.3](https://github.com/tjirab/tff/compare/tff-core-v0.2.2...tff-core-v0.2.3) (2026-06-28)


### Features

* add tff health command for project health reporting ([#60](https://github.com/tjirab/tff/issues/60)) ([264114a](https://github.com/tjirab/tff/commit/264114a6ae07675d750b1bf134260bcb1ad83d21))
* check to limit view nesting depth in DAG ([#25](https://github.com/tjirab/tff/issues/25)) ([#57](https://github.com/tjirab/tff/issues/57)) ([01f2d09](https://github.com/tjirab/tff/commit/01f2d09d713c46b2c4b0c49258b7a53d3f652031))
* unify CLI commands into tff lint ([#59](https://github.com/tjirab/tff/issues/59)) ([2f4cd01](https://github.com/tjirab/tff/commit/2f4cd01803ea595666208df16c705bb234084b34))

## [0.2.2](https://github.com/tjirab/tff/compare/tff-core-v0.2.1...tff-core-v0.2.2) (2026-06-27)


### Features

* add EnvironmentAgnosticReferences rule to ban hardcoded environments ([#55](https://github.com/tjirab/tff/issues/55)) ([f408f03](https://github.com/tjirab/tff/commit/f408f03cdd11e01aa7efa54c0acebf33d9a1fba0))
* make SQL dialect mandatory and remove bigquery defaults ([#52](https://github.com/tjirab/tff/issues/52)) ([f8528aa](https://github.com/tjirab/tff/commit/f8528aad2febb9e1c2a9f8aa554f2b51fff9bbb8))
* rename no_select_star rule to ban_select_star ([#54](https://github.com/tjirab/tff/issues/54)) ([0928958](https://github.com/tjirab/tff/commit/09289587aa13dc24a9cdb139d2a4da050f6b4f9e))
* resolve jinja parsing and unique test mapping in tff-dbt ([#49](https://github.com/tjirab/tff/issues/49)) ([2e14962](https://github.com/tjirab/tff/commit/2e14962d6407496b249c6158eaf40d74860e663b))

## [0.2.1](https://github.com/tjirab/tff/compare/tff-core-v0.2.0...tff-core-v0.2.1) (2026-06-27)


### Features

* migrate repository to tff monorepo with core, sqlmesh, and dbt packages ([#39](https://github.com/tjirab/tff/issues/39)) ([d622758](https://github.com/tjirab/tff/commit/d622758e1ff20ba7153bdbe7d816357ce72ecfd5))
