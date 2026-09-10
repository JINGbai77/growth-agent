# Contributing

Use Python 3.11 or newer and install `requirements-dev.lock` plus the editable package. Before a
change, run `ruff format --check .`, `ruff check .` and `pytest`.

Analytical changes should add or update a seeded scenario, compare against an explicit baseline,
and state which rows are eligible for scoring. Never present simulated metrics as production
outcomes. Changes to attribution must preserve the exact contribution-sum invariant. Changes to
experiment decisions must test low counts, sample-ratio mismatch, incomplete horizons and multiple
comparisons. Model-backed features must retain an offline path and validate external output.

Do not commit `.env`, API keys, local databases, generated reports or user datasets.
