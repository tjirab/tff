# Design System & Style Guide

A rationalist specification for CLI aesthetics, information architecture, documentation, and interface typography across the `tff` ecosystem.

See the complete [Style Guide & Design System](docs/style_guide.md) for full specifications.

---

## Core Philosophy: Style Follows Function

1. **Functional Necessity**: Every visual element, layout delimiter, and character must serve a concrete operational purpose. Pure decoration is eliminated.
2. **Prohibition of Decorative Iconography**: Zero emojis across documentation, PR templates, commit messages, and CLI streams. Status is expressed through semantic text (`PASS`, `FAIL`, `WARN`) or geometric glyphs (`●`, `─`, `├─`, `└─`, `[+]`, `[-]`).
3. **Constructivist Grid**: Tables, tree branches, and coordinates adhere to strict geometric alignment for rapid optical scanning.
4. **Monochromatic Contrast**: High-contrast typography with purposeful semantic accents (red for errors, yellow for warnings, green for passing checks, cyan for hyperlinks).
5. **Technical Prose**: Economical, declarative documentation without conversational filler or marketing superlatives.

---

## Surface Standards

### Pull Request Templates (`.github/pull_request_template.md`)
- `## Summary`: Direct synopsis of the pull request.
- `## Motivation & Context`: Underlying defect, requirement, or architectural driver.
- `## Structural Changes`: Itemized modifications to code, configuration, or documentation.
- `## Verification & Quality Gates`: Executable commands validating unit tests, linting, and 100% diff coverage.
- `## Traceability`: Explicit issue or contract linkage.

### Documentation & README Layout
- Direct title and functional summary.
- Standardized tabular feature matrices.
- Minimalist terminal session codeblocks.
- Monospace formatting for coordinates (`path:line:col`) and identifiers.

### CLI Rendering
- Tree-structured branches (`├─`, `└─`, `│`) connecting models to findings.
- Numeric progress meters (`████████░░ 80.0%`).
- Single-line concise check summaries with actionable hints for auto-remediation.
