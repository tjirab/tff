# Functional Design System & Style Guide

A rationalist specification for CLI aesthetics, information architecture, documentation, and interface typography.

---

## 1. Core Philosophy: Style Follows Function

The visual and structural presentation of software must derive directly from its operational purpose. Style is not an aesthetic layer applied after engineering; style is the physical structure of functional clarity.

### Primary Principles

1. **Style Follows Function**: Visual treatment must serve comprehension, scannability, and operational utility. Purely decorative elements that do not convey data are eliminated.
2. **Rationalism and Structural Geometry**: Layouts are governed by visible grids, clear geometric boundaries, and disciplined spatial relationships.
3. **Information Density without Chaos**: Maximize signal-to-noise ratio. Eliminate visual clutter while maintaining high data density.
4. **Honesty of Medium**: Text is text; code is code; terminal output is terminal output. Avoid artificial metaphors, faux textures, or skeuomorphic decorations.

---

## 2. Prohibition of Decorative Iconography (Zero Emojis)

Extraneous iconography and emojis are strictly prohibited across all project surfaces.

### Surface Scope

This rule applies universally across:
- Pull Request templates, titles, and descriptions.
- Documentation, README files, and architectural guides.
- Git commit messages, branch names, and tags.
- Terminal outputs, CLI logs, error messages, and progress displays.

### Rationale

- **Optical Inconsistency**: Emojis render with disparate color palettes, inconsistent line heights, and unpredictable bounding boxes across operating systems (macOS, Linux, Windows) and terminal emulators.
- **Cognitive Distraction**: Emojis dilute technical rigor, introducing whimsical noise that obscures critical architectural alerts.
- **Accessibility Degradation**: Screen readers pronounce emoji descriptions verbatim, disrupting natural reading flow for visually impaired engineers.

### Functional Substitutions

Replace decorative iconography with semantic text tokens or standard geometric markers:

| Prohibited Decorative Pattern | Functional Replacement | Purpose |
| :--- | :--- | :--- |
| Decorative rocket / "What changed?" | `## Summary` or `## Structural Changes` | Section heading |
| Decorative thinking face / "Why is this needed?" | `## Motivation & Context` | Section heading |
| Decorative link icon / "Related Issues" | `## Traceability` | Section heading |
| Decorative checkmark / "Next Steps / Checklist" | `## Verification & Quality Gates` | Section heading |
| Decorative lightning bolt / "Quickstart" | `## Quickstart (Zero Configuration)` | Section heading |
| Decorative error/cross emojis | `ERR`, `FAIL`, `[FAIL]` | Error status |
| Decorative warning emojis | `WRN`, `WARN`, `[WARN]` | Warning status |
| Decorative check/party emojis | `PASS`, `OK`, `[PASS]` | Pass status |
| Decorative magnifying glass/graph emojis | `[SCAN]`, `[METRICS]`, `●` | Progress indicator |

---

## 3. Typographic Discipline & Structural Hierarchy

Typography serves as the primary architectural element of the interface.

### Heading Architecture

- **Document Title (`#`)**: Reserved for the singular top-level system or component title. Unadorned, clear, and direct.
- **Functional Sections (`##`)**: Major operational boundaries (e.g., `## Architecture`, `## Execution`, `## Verification`).
- **Sub-components (`###`)**: Granular subsections or detailed configuration parameters.
- **Minimal Punctuation**: Headings must not contain trailing colons, emojis, exclamation points, or conversational questions.

### Monospace Formatting

Use monospace typography for all machine-readable coordinates, identifiers, and executable commands:
- File paths and coordinates: `models/core/users.sql:42:1`
- Rule identifiers: `banselectstar`, `layer_integrity`, `duplicate_ctes`
- Commands and flags: `tff check --verbose`, `uv run pytest`
- Configuration keys: `fail-under`, `models_checked`

### Weight & Contrast

- Use **strong bolding** solely for field keys, column headers, and structural anchors.
- Use regular weight for narrative descriptions and technical explanations.
- Avoid italicizing large blocks of text; italics are reserved for mathematical variables or formal Latin taxonomy.

---

## 4. Constructivist Grid & Spatial Composition

Layouts must adhere to consistent grid structures and predictable alignments.

### Tabular Alignment

Tables must be formatted as precise grids. Left-align text labels; right-align numerical values, scores, and timestamps:

```markdown
| Metric | Value | Threshold | Status |
| :--- | ---: | ---: | :--- |
| Architectural Health Score | 87.4% | 80.0% | PASS |
| Models Audited | 142 | — | OK |
| Execution Latency | 0.42s | 2.00s | PASS |
```

### Tree Structures & Coordinate Branches

Hierarchical output must utilize clean branch characters (`├─`, `└─`, `│`) to reflect parent-child relationships:

```text
● models/core/dim_users.sql
  ├─ 42:1   ERR   banselectstar   SELECT * is prohibited.
  └─ 58:12  WRN   nomissingowner  Owner attribute is required.
```

### Whitespace as a Structural Element

- Use vertical whitespace intentionally to delimit logical processing stages.
- Employ clean horizontal rules (`---`) to separate major thematic modules.
- Maintain consistent padding between code blocks, tables, and narrative paragraphs.

---

## 5. Monochromatic Foundation & Semantic Accents

Color must be utilized exclusively as functional information, never as decorative tinting.

- **Monochromatic Base**: Content is framed on a stark monochromatic foundation (high contrast black, white, slate).
- **Red (`#E06C75` / ANSI Red)**: Reserved strictly for blocking errors, test failures, and illegal DAG violations.
- **Amber / Yellow (`#E5C07B` / ANSI Yellow)**: Reserved for non-blocking warnings, deprecation notices, and advisory thresholds.
- **Green (`#98C379` / ANSI Green)**: Reserved for clean passing checks and verified quality gates.
- **Cyan / Blue (`#61AFEF` / ANSI Blue)**: Reserved for interactive terminal hyperlinks (`file://`, `https://`) and navigation targets.

---

## 6. Information Architecture & Technical Prose

Documentation and pull requests must communicate with direct, objective, and economical language.

1. **Omit Conversational Fluff**: Eliminate greetings, rhetorical questions, and marketing superlatives ("awesome", "supercharged", "magical").
2. **Active, Declarative Tone**: State what a component does, why it exists, and how to verify it.
3. **Structured Anatomy**: Every operational document should follow a predictable sequence:
   - **Specification**: What does this module or pull request achieve?
   - **Context**: What problem or architectural constraint necessitated it?
   - **Implementation**: What concrete changes were introduced?
   - **Verification**: How is correctness validated through automated tests?

---

## 7. Quality Gate & Conformance Checklist

Prior to submitting pull requests or publishing documentation, verify conformance against this checklist:

- [ ] Zero emojis across PR title, PR description, commit messages, and modified files.
- [ ] Section titles are declarative and free of whimsical phrasing.
- [ ] Code coordinates, rule names, and CLI flags use monospace formatting.
- [ ] Tables and output trees use proper geometric alignment.
- [ ] Testing commands, linter checks, and diff coverage requirements are explicitly documented.
