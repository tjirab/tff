# Changelog

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
