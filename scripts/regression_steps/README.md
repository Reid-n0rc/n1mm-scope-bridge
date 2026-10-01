# Release regression steps

One file per check, run in filename order by `scripts/release_regression.py`
(issue #45). Each file defines:

```python
from regression_core import Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    return [Step("My check", ("uv", "run", "something"))]
```

- Name files `NN_name.py`. The number sets the order; leave gaps (10, 20, …).
- A feature adds its own step file in the same PR (AGENTS.md → Release
  process). Never edit another lane's step file.
- Placeholder steps for features that haven't landed use
  `disabled_reason="added by #<issue>"`, which the release allows.
- Shared helpers go in `scripts/regression_core.py`. Tests for a step go in
  `tests/scripts/regression_steps/test_step_<name>.py`.
