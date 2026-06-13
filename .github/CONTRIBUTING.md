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
a whole, because you're coming to the project with fresh eyes, so you can see the
errors and assumptions that seasoned contributors have glossed over.

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

Folium uses pytest markers to categorize tests.  The marker rules are
**enforced at collection time** by the `pytest_collection_modifyitems` hook
in [tests/conftest.py](file:///Users/pkcha/folium/tests/conftest.py) – if
you break them, `pytest` exits immediately with code 4, before any test runs.

### Markers

| Marker | Kind | Description | Default | Dependencies |
|--------|------|-------------|---------|--------------|
| `core` | category | Fast unit tests for folium core (features, map, utilities, …) | ✅ runs | none |
| `plugins` | category | Tests for `folium.plugins.*` | ✅ runs | none |
| `external_data` | gate | Needs `geodatasets`, network, or remote APIs | ❌ skip | `geodatasets`, network |
| `render` | gate | PNG diff with `pixelmatch` against golden screenshots | ❌ skip | `pixelmatch`, `pillow`, `selenium` |
| `selenium` | gate | Browser automation via Selenium / Chrome | ❌ skip | `selenium`, Chrome |

- **Category** markers select a subset with `-m`.  Every test must carry
  exactly one.
- **Gate** markers are opt-in: without the matching `--run-*` flag the test
  is SKIPPED.  They can only be added **on top of** a category marker.

### Writing New Tests

1. **Pick exactly one category** and set it at the file level:
   ```python
   import pytest
   pytestmark = pytest.mark.core       # tests/foo.py
   # OR
   pytestmark = pytest.mark.plugins    # tests/plugins/test_xxx.py
   ```
   - `core` → tests of non-plugin code in `folium/`
   - `plugins` → tests of anything under `folium.plugins/`
   - You may **not** mark with both; you may **not** omit the category.

2. **Gate markers are overlays only** – add them to individual functions:
   ```python
   pytestmark = pytest.mark.core

   @pytest.mark.external_data          # overlay on one test
   def test_something_that_uses_geodatasets():
       ...
   ```

3. **Special directories** (`tests/selenium/`, `tests/snapshots/`) have
   their own conventions – see `pytest_collection_modifyitems` in
   [tests/conftest.py](file:///Users/pkcha/folium/tests/conftest.py).

### Marker Audit

The single entry point for structural checks is:

```bash
python scripts/marker-audit
# or via tox:
tox -e marker-audit
```

This runs **no test code** – it only collects items and verifies every
test carries the right markers.  If it exits with code 4, read the error
message to find which test is missing which marker.

Every tox environment declares `depends = marker-audit`, so `tox` (without
`-e`) always runs the audit first.  Every CI workflow also calls
`python scripts/marker-audit` as a "Marker audit" step before executing
any tests.  The command is defined in **one place** only
([scripts/marker-audit](file:///Users/pkcha/folium/scripts/marker-audit));
tox and CI never duplicate the raw pytest invocation.

### Running Tests

```bash
# Default: core + plugins (fast, offline, no browser).
python -m pytest tests --ignore=tests/selenium --ignore=tests/snapshots

# Also run external-data tests.
python -m pytest tests --ignore=tests/selenium --ignore=tests/snapshots --run-external-data

# PNG snapshot tests.
python -m pytest tests/snapshots --run-render --run-selenium --run-external-data

# Browser automation tests.
python -m pytest tests/selenium --run-selenium --run-external-data

# Everything.
python -m pytest tests --run-all
```

### Using Tox

```bash
tox -e marker-audit    # structural audit only (no tests execute)
tox -e quick           # fastest inner loop: core + plugins, compact output
tox -e py              # default: core + plugins
tox -e py-external     # default + external_data
tox -e py-render       # PNG snapshot tier
tox -e py-selenium     # browser automation tier
tox -e py-all          # everything
tox -e release-check   # everything + mypy
```

### CI Trigger Labels

| PR label | Workflow |
|----------|----------|
| `run-selenium` | [test_selenium.yml](file:///Users/pkcha/folium/.github/workflows/test_selenium.yml) |
| `run-render` | [test_snapshots.yml](file:///Users/pkcha/folium/.github/workflows/test_snapshots.yml) |

[test_code.yml](file:///Users/pkcha/folium/.github/workflows/test_code.yml)
always runs `core + plugins` on every PR and push; its `external_data` job
runs on push to `main` and on the daily schedule.

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
