# Development

Use Python 3.14, matching CI and the pinned Home Assistant test dependencies.
From the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows, use `py -3.14 -m venv .venv` and `.venv\Scripts\python.exe`
for the corresponding commands.

## VS Code and Pylance

Open the repository folder and install the Python and Pylance extensions.
The workspace settings default to `.venv` and analyze the whole workspace.
If VS Code already selected another interpreter, run **Python: Select
Interpreter** and choose this repository's `.venv`. Run **Python: Restart
Language Server** if diagnostics have not refreshed.

`pyrightconfig.json` enables strict checking for the integration, all Python
tests (including the hardware tests), the documentation hook, and local stubs.
Pyright provides a command-line check using the type engine behind Pylance:

```sh
.venv/bin/pyright
```

Fixture parameters need explicit types: for example,
`mock_config_entry: MockConfigEntry` and `hass: HomeAssistant`. Test helpers in
`tests/typing.py` check optional values and mocked methods before using them.
Keep annotations specific; `Any` is used at dynamic MessagePack, service-payload,
and mock boundaries.

The configuration has these documented exceptions:

- Tests intentionally inspect private implementation details, and some test
  dependencies lack a `py.typed` marker. Only private-access and missing-stub
  diagnostics are disabled for tests; unknown types still produce errors.
- Home Assistant's entity mixins use `cached_property` descriptors. Dynamic
  coordinator properties must be recomputed, so the entity platform modules
  disable the incompatible-variable-override diagnostic.
- Individual calls with incomplete upstream annotations have narrow inline
  exceptions. Unnecessary inline exceptions are errors, so they can be removed
  when upstream annotations improve.
- `typings/aioresponses/__init__.pyi` describes the HTTP mock API used by these
  tests, including its request history. Review it when upgrading aioresponses.

## Validation

```sh
.venv/bin/black --check custom_components/ tests/ docs_macros.py typings/
.venv/bin/pyright
.venv/bin/mypy --strict --ignore-missing-imports custom_components/sunriser/
.venv/bin/pytest tests/ --ignore=tests/test_device.py --cov=custom_components/sunriser --cov-report=term-missing --cov-fail-under=100
node --test tests/frontend/*.test.cjs
.venv/bin/mkdocs build --strict
```

The normal unit suite mocks controller traffic. `tests/test_device.py` is a
separate hardware/simulator suite with write and reboot operations; it is
included in type checking but excluded from the normal test command and CI.
See its module docstring for explicit device-test instructions.
