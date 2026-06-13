# Contributing

We love contributions!  folium is open source, built on open source,
and we'd love to have you hang out in our community.

**Impostor syndrome disclaimer**: We want your help. No, really.

There may be a little voice inside your head that is telling you that you're not
ready to be an open source contributor; that your skills aren't nearly good
enough to contribute. What could you possibly offer a project like this one?

We assure you - the little voice in your head is wrong. If you can write code at
all, you can contribute code to open source. Contributing to open source
projects is a fantastic way to advance one's coding skills. Writing perfect code
isn't the measure of a good developer (that would disqualify all of us!); it's
trying to create something, making mistakes, and learning from those
mistakes. That's how we all improve, and we are happy to help others learn.

Being an open source contributor doesn't just mean writing code, either. You can
help out by writing documentation, tests, or even giving feedback about the
project (and yes - that includes giving feedback about the contribution
process). Some of these contributions may be the most valuable to the project as
a whole, because you're coming to the project with fresh eyes, so you can see
the errors and assumptions that seasoned contributors have glossed over.

(This disclaimer was originally written by
[Adrienne Lowe](https://github.com/adriennefriend) for a
[PyCon talk](https://www.youtube.com/watch?v=6Uj746j9Heo), and was adapted by folium
based on its use in the README file for the
[yt project](https://github.com/yt-project/yt/blob/master/README.md))

## Usage questions

The best place to submit questions about how to use folium is via the
[gitter](https://gitter.im/python-visualization/folium) channel or on
[Stackoverflow](https://stackoverflow.com/questions/tagged/folium).
Usage question in the issue tracker will probably go unanswered.

## Reporting issues

When reporting issues please include as much detail as possible regarding the folium and python version, use of notebooks, errors in Python, errors in your browser console, etc.
Whenever possible, please also include a [short, self-contained code example](http://sscce.org) that demonstrates the problem. Don't forget a data snippet or link to your dataset.

## Contributing code

First of all, thanks for your interest in contributing!

If you are new to git/Github, please take check a few tutorials
on [git](https://git-scm.com/docs/gittutorial) and [GitHub](https://guides.github.com/).

The basic workflow for contributing is:

1. [Fork](https://help.github.com/articles/fork-a-repo/) the repository
2. [Clone](https://help.github.com/articles/cloning-a-repository/) the repository to create a local copy on your computer:
   ```
   git clone git@github.com:${user}/folium.git
   cd folium
   ```
3. Create a branch for your changes
   ```
   git checkout -b name-of-your-branch
   ```
4. Install the [miniconda](https://docs.conda.io/en/latest/miniconda.html) to avoid any external library errors.

   If using `conda` one can create a development environment with:
   ```
   $ conda create --name FOLIUM -c conda-forge python=3 --file requirements.txt --file requirements-dev.txt
   ```
5. Install the dependencies listed in `requirements.txt` and `requirements-dev.txt`.
   ```
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
6. In Python run `pre-commit install` to enable the commit hooks that run our linter.
7. Make changes to your local copy of the folium repository
8. Make sure the tests pass:
   * in the repository folder do `pip install -e . --no-deps`  (needed for notebook tests)
   * see [Test Categories and Markers](#test-categories-and-markers) below for how to run different test categories
9. Commit those changes
    ```
    git add file1 file2 file3
    git commit -m 'a descriptive commit message'
    ```
10. Push your updated branch to your fork
   ```
   git push origin name-of-your-branch
   ```
11. [Open a pull request](https://help.github.com/articles/creating-a-pull-request/) to the python-visualization/folium

Since we're all volunteers please help us by making your PR easy to review. That means having a clear description and only touching code that's necessary for your change.

## Test Categories and Markers

Folium uses pytest markers to categorize tests by stability, speed, and dependencies.
This allows you to run only the tests you need, and avoids failures from missing
optional dependencies or network issues.

### Available Markers

Markers are registered in both
[pyproject.toml](file:///Users/pkcha/folium/pyproject.toml) (under
`[tool.pytest.ini_options].markers`) and
[tests/conftest.py](file:///Users/pkcha/folium/tests/conftest.py)
(via `pytest_configure`).  They come in two flavours:

| Marker | Type | Description | Default | Dependencies |
|--------|------|-------------|---------|--------------|
| `core` | **category** | Fast, stable unit tests for folium core (features, map, utilities, vector_layers, …) | ✅ Runs by default | None |
| `plugins` | **category** | Tests for `folium.plugins.*` (stable HTML-rendering tests) | ✅ Runs by default | None |
| `external_data` | **gate** | Requires `geodatasets`, live `requests` calls, or remote APIs. Needs `--run-external-data`. | ❌ Skipped | `geodatasets`, network |
| `render` | **gate** | Slow PNG rendering with `pixelmatch` against golden screenshots. Needs `--run-render`. | ❌ Skipped | `pixelmatch`, `pillow`, `selenium` |
| `selenium` | **gate** | Browser automation driven by Selenium / Chrome. Needs `--run-selenium`. | ❌ Skipped | `selenium`, Chrome webdriver |

A **category** marker is informational: you combine it with `-m` to *select* a
subset (e.g. `-m plugins`).  A **gate** marker is opt-in: without the matching
`--run-*` CLI flag the test is SKIPPED, regardless of `-m`.

### Skip-Reason Cheat-Sheet

`pytest -ra` prints all skip reasons at the end.  Recognise these two patterns:

| Reason prefix | Meaning | What to do |
|---------------|---------|------------|
| `external_data: pass --run-external-data or --run-all` | Opt-in gate not enabled. | Pass the flag, or ignore (intended for local dev). |
| `render: pass --run-render or --run-all` | Same, for the render gate. | Pass the flag. |
| `selenium: pass --run-selenium or --run-all` | Same, for the selenium gate. | Pass the flag. |
| `… --run-<tier> passed but <dep> is not installed (pip install …)` | You explicitly asked for the tier, but the machine is missing a Python package. | Install the dependency named in the message. |

The distinction matters: the first group is “you asked for a smaller set”, the
second is “you asked for the full set but the environment is incomplete”.
Neither means your code is broken.  If `core` / `plugins` tests fail, *that* is
a code regression.

### Writing New Tests

**Every test you add MUST be marked.**  The CI marker-audit step (and the
`pytest_collection_modifyitems` hook in [tests/conftest.py](file:///Users/pkcha/folium/tests/conftest.py))
will *hard-fail* collection (exit code 4) if any of these rules are broken:

1. **Pick exactly one category marker** and apply it at the file level, as
   early as possible after the imports:
   ```python
   import pytest

   pytestmark = pytest.mark.core       # for tests/foo.py under core modules
   # OR
   pytestmark = pytest.mark.plugins    # for tests/plugins/test_xxx.py
   ```
   - Use `@pytest.mark.core` for tests of non-plugin code in `folium/`
     (features, map, utilities, vector_layers, etc.)
   - Use `@pytest.mark.plugins` for tests of anything under `folium.plugins/`.
   - You may *not* mark with both; you may *not* omit the category.

2. **Gate markers are overlays only.**  `@pytest.mark.external_data`,
   `@pytest.mark.render`, and `@pytest.mark.selenium` can only be added to
   *individual test functions* (or classes) that already live in a
   `@pytest.mark.core` or `@pytest.mark.plugins` file.  They cannot be used
   as the sole marker on a test.  Example:
   ```python
   pytestmark = pytest.mark.core   # file-level category

   @pytest.mark.external_data      # overlay on one test only
   def test_something_that_uses_geodatasets():
       ...
   ```

3. **Special directories** (`tests/selenium/`, `tests/snapshots/`) have
   their own conventions – see the header comment in
   [tests/conftest.py](file:///Users/pkcha/folium/tests/conftest.py)
   `pytest_collection_modifyitems`.  If you are not adding a test to one of
   those directories, you can ignore this rule.

If `tox -e marker-audit` passes, your markers are correct.  If it fails, read
the error message carefully – it tells you which test is missing which marker.

### Running Tests

```bash
# Default: run core + plugins tests (fast, stable, no network, no browser).
# Gate-tagged tests (external_data/render/selenium) will show as SKIPPED.
python -m pytest tests --ignore=tests/selenium --ignore=tests/snapshots

# Also run tests that hit geodatasets or the network.
python -m pytest tests --ignore=tests/selenium --ignore=tests/snapshots --run-external-data

# Run PNG snapshot tests (needs selenium + pixelmatch + pillow + Chrome).
python -m pytest tests/snapshots --run-render --run-selenium --run-external-data

# Run browser automation tests.
python -m pytest tests/selenium --run-selenium --run-external-data

# Run EVERYTHING (all gates open).
python -m pytest tests --run-all

# Selection examples using markers (-m).
python -m pytest tests -m "core"                     # only core
python -m pytest tests -m "plugins"                  # only plugins
python -m pytest tests -m "core or plugins"          # default tier (same as no -m)
python -m pytest tests -m "not external_data"        # exclude a gate
python -m pytest tests -m "plugins and not external"  # only stable plugins
```

### Using Tox

[tox.ini](file:///Users/pkcha/folium/tox.ini) documents every environment with
a tier matrix comment block at the top.

```bash
# Default tests (core + plugins).  This is what every PR runs in CI.
tox -e py

# Static marker audit first – catch missing/incorrect markers without
# running any tests.  Always run this after adding new test files.
tox -e marker-audit

# Default + external_data (geodatasets + network).
tox -e py-external

# PNG pixelmatch snapshot tier (selenium + pixelmatch + pillow).
tox -e py-render

# Selenium browser tier.
tox -e py-selenium

# All tiers combined.
tox -e py-all

# Fastest inner-loop run (compact output, no gate-tagged tests collected).
tox -e quick

# Pre-release gate: all tiers + mypy type-checking.
tox -e release-check
```

### CI Trigger Labels

For pull requests, optional tiers (render, selenium) are skipped by default to
keep feedback fast.  Add a label to force them to run for your PR:

- `run-selenium` → triggers [test_selenium.yml](file:///Users/pkcha/folium/.github/workflows/test_selenium.yml)
- `run-render` → triggers [test_snapshots.yml](file:///Users/pkcha/folium/.github/workflows/test_snapshots.yml)

The main [test_code.yml](file:///Users/pkcha/folium/.github/workflows/test_code.yml)
always runs `core + plugins` on every PR and push.  Its `external_data` job
runs on push to `main` and on the daily schedule.  The full tier-to-job matrix
is documented in the header of that file.

## Plugin acceptance criteria

If you have a Leaflet plugin you would like to include in folium's plugins, please
check these criteria to see if it's a good candidate.

Criteria for the Leaflet plugin:
- the plugin provides interesting new functionality.
- the plugin is not abandoned. It's okay if not all issues or PR's are being
  processed, as long as there are no critical bugs or fixes being ignored.

Criteria for the Python wrapper:
- the template is simple.
- the class has not much logic, just passing some things to the template.
- no/little integration with other folium classes.

As well as these criteria for the process:

- the contributor communicates well.
- the PR is of reasonably good quality.

The *final* PR should contain:

- a new module in `folium/plugins` with the plugin class, with docstring
- importing that class in `folium/plugins/__init__.py`
- a test in `tests/plugins/test_[new plugin module].py`
- a documentation module with examples in `docs/user_guide/plugins`
- listing that module in `docs/user_guide/plugins.rst`
  - in the toctree
  - as well as the table lower on the page

Before doing all this work it's a good idea to open a PR with just the plugin
to discuss whether it's something to include in folium.

If your plugin is not a good fit for folium, you should consider publishing your
plugin yourself! We can link to your plugin so users can find it.
