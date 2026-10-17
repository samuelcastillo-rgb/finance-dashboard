# Agent Instructions

## Project Scope

- This workspace contains small Python functions for financial-ratio analysis using Yahoo Finance data.
- Keep changes focused on calculation behavior and preserve the existing Spanish naming and comments unless the task requires otherwise.
- Source filenames may contain spaces and mixed casing; do not rename them casually because import paths may depend on them.

## Dependencies and Execution

- `yfinance` is the primary external dependency. `pandas` is present in some modules but is not a documented project dependency yet.
- There is no package configuration, test suite, CLI, or documented entry point. Validate changes by importing the affected module and exercising the changed function with a small controlled object or fixture.
- Most modules expose functions only; do not add top-level network calls or execution side effects.

## Coding Conventions

- Follow the existing `snake_case` function style and preserve public function names unless a rename is explicitly requested.
- Financial data is read from Yahoo Finance-style `financials` and `balance_sheet` data frames. Handle missing statement rows consistently with the surrounding function.
- Keep edits minimal. Avoid broad refactors, new frameworks, and unrelated formatting changes.
- Add tests or a small reproducible validation script when a change affects ratio calculations; do not commit generated `__pycache__` artifacts.

## Font Family and Presentation

- This repository currently has no UI, HTML/CSS, plotting, or terminal presentation layer. Do not add font packages, font configuration, or presentation abstractions to calculation modules.
- If a future task introduces a report, dashboard, or visualization, keep font-family decisions in that presentation layer and document the chosen font and fallback stack there. Do not let display concerns leak into financial calculations.