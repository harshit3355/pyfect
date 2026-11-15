"""CI runs the project's full check, and a release publishes only after CI, its extras and the
docs pass.

The check line in CLAUDE.md is what "done" means locally; CI's `lint`, `types` and `test` jobs
must run the same four tools, or a commit green on one machine is red on the other.
"""

import json
import re
from pathlib import Path

from pyfect.date_time._icu_zones import NODE_VERSION

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _job(workflow: str, name: str) -> str:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text)
    assert match, f"{workflow} has no job {name!r}"
    return match.group(1)


def test_ci_runs_the_check_in_claude_md():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(ln for ln in claude.splitlines() if "uv run ruff format" in ln)
    tools = [part.split()[2] for part in line.strip().split("&&")]
    assert tools == ["ruff", "ruff", "pyright", "pytest"], line
    lint, types, test = _job("ci.yml", "lint"), _job("ci.yml", "types"), _job("ci.yml", "test")
    for command in ('uvx "$ruff" format --check .', 'uvx "$ruff" check .'):
        assert command in lint, f"ci.yml's lint job does not run `{command}`"
    assert 'p["name"] == "ruff"' in lint, "lint runs the ruff uv.lock pins"
    assert "uv run --no-sync pyright" in types, "ci.yml's types job does not run pyright"
    assert "uv run --no-sync pytest" in test, "ci.yml's test job does not run the tests"
    for job in (types, test, _job("ci.yml", "collect")):
        assert "uses: ./.github/actions/check-setup" in job
    for job in (test, _job("ci.yml", "collect")):
        assert "PYFECT_EFFECT_REF" in job, "the oracle tests need Effect's checkout"


def test_one_pyright_run_checks_every_python():
    """Pyright analyses for pyproject's pythonVersion whatever runs it; the types job syncs that
    Python."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'(?m)^pythonVersion = "(3\.\d+)"$', pyproject)
    assert version, "pyproject.toml pins pyright's pythonVersion"
    assert f'python: "{version.group(1)}"' in _job("ci.yml", "types")


def test_the_shards_run_every_test_once_and_the_check_says_so():
    """The tests run split across runners; `check (3.x)`, the name branch protection requires,
    passes only if every job passed and the shards' tests are a full collection's."""
    test = _job("ci.yml", "test")
    shards = re.search(r"(?m)^\s+shard: \[(.*)\]$", test)
    assert shards, "ci.yml's test job has no shard matrix"
    count = len(shards.group(1).split(","))
    assert shards.group(1) == ", ".join(str(k) for k in range(1, count + 1))
    assert f"name: test (${{{{ matrix.python }}}}, ${{{{ matrix.shard }}}}/{count})" in test
    run = re.search(r"(?ms)- name: Tests\n\s+run: \|\n(.*?)\n\n", test)
    assert run, "ci.yml's test job has no Tests step"
    assert f"--shard ${{{{ matrix.shard }}}}/{count} " in run.group(1)
    for narrowing in (" -k ", " -m ", "--deselect", "--ignore", " -x", "--maxfail", "--lf"):
        assert narrowing not in run.group(1), f"the shards must run every test: {narrowing}"
    assert "--shard-manifest .shards/shard-${{ matrix.shard }}.txt" in run.group(1)
    assert "name: manifest-${{ matrix.python }}-${{ matrix.shard }}" in test

    collect = _job("ci.yml", "collect")
    assert "--collect-only -p no:randomly --shard-manifest .shards/full.txt" in collect
    assert "name: manifest-${{ matrix.python }}-full" in collect

    check = _job("ci.yml", "check")
    jobs = ["lint", "types", "collect", "test"]
    assert f"needs: [{', '.join(jobs)}]" in check
    # A required check that is skipped counts as passed, so it must run when a job failed.
    assert "if: always()" in check
    for job in jobs:
        assert f"${{{{ needs.{job}.result }}}}" in check, job
        assert f'[ "${job.upper()}" = success ]' in check, job
    assert "pattern: manifest-${{ matrix.python }}-*" in check
    assert "scripts/test_shards.py verify .shards/full.txt .shards/shard-*.txt" in check


def test_a_branch_push_checks_its_pull_request():
    """A pull request from this repository's own branch gets its checks from the push of that
    branch (the same commit); its pull_request run would only double the runners. A fork's runs
    here."""
    for workflow in ("ci.yml", "audit.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
        for job in jobs:
            condition = re.search(r"(?m)^    if: (.*)$", _job(workflow, job))
            assert condition, f"{workflow}'s {job} has no condition"
            assert (
                "github.event_name != 'pull_request' || github.event.pull_request.head.repo.fork"
                in condition.group(1)
            ), f"{workflow}'s {job}"


def test_the_docs_build_check_passes_only_if_every_docs_job_did():
    """`build` is the docs check branch protection requires; the work runs in parallel jobs."""
    text = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
    others = [job for job in jobs if job != "build"]
    build = _job("docs.yml", "build")
    assert f"needs: [{', '.join(others)}]" in build
    assert "if: always()" in build
    for job in others:
        assert f"${{{{ needs.{job}.result }}}}" in build, job
    assert build.count("= success ]") == len(others)


def test_extras_gate_benchmarks_and_free_threaded():
    job = _job("extras.yml", "benchmarks")
    assert "gate.py" in job
    # The comparison with the branch base needs the history to find it.
    assert "python compare.py\n" in job and "fetch-depth: 0" in job
    assert "3.14t" in _job("extras.yml", "free-threaded")


def test_the_extras_check_waits_for_every_extra_that_runs():
    """`extras` passes only if every extra passed, or none ran because this run doesn't run
    them; each extra and the check decide that with one condition."""
    text = (WORKFLOWS / "extras.yml").read_text(encoding="utf-8")
    runs = re.search(r"(?m)^  RUNS_EXTRAS: \$\{\{ (.*) \}\}$", text)
    assert runs, "extras.yml defines RUNS_EXTRAS"
    jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
    extras = [job for job in jobs if job != "extras"]
    for job in extras:
        assert f"    if: {runs.group(1)}\n" in _job("extras.yml", job), job
    check = _job("extras.yml", "extras")
    assert f"needs: [{', '.join(extras)}]" in check and "if: always()" in check
    for job in extras:
        assert f"${{{{ needs.{job}.result }}}}" in check, job
    # Never on a pull request, always on main, in the merge queue and for a release.
    assert runs.group(1).startswith("github.event_name != 'pull_request' && (")
    assert "github.ref == 'refs/heads/main'" in runs.group(1)
    assert "startsWith(github.ref, 'refs/tags/')" in runs.group(1)


def test_runs_on_main_tags_and_the_merge_queue_are_never_cancelled():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        cancel = re.search(r"(?m)^  cancel-in-progress: (.*)$", text)
        if cancel is None or cancel.group(1) == "false":
            continue
        assert cancel.group(1) == (
            "${{ github.event_name == 'pull_request' || (github.event_name == 'push' && "
            "github.ref != 'refs/heads/main' && !startsWith(github.ref, 'refs/tags/')) }}"
        ), path.name


def test_every_check_main_needs_runs_in_the_merge_queue():
    for workflow in ("ci.yml", "extras.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert re.search(r"(?m)^  merge_group:$", text), workflow


def test_every_ci_job_has_a_time_budget():
    """A job's timeout is its budget: one that grows past it fails instead of slowing every
    run down."""
    for workflow in ("ci.yml", "extras.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
        for job in jobs:
            budget = re.search(r"(?m)^    timeout-minutes: (\d+)$", _job(workflow, job))
            assert budget, f"{workflow}'s {job} has no timeout-minutes"


def test_a_release_needs_ci_its_extras_and_the_docs():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for job in ("ci", "extras", "docs"):
        assert f"uses: ./.github/workflows/{job}.yml" in _job("release.yml", job)
        assert "workflow_call:" in (WORKFLOWS / f"{job}.yml").read_text(encoding="utf-8")
    assert re.search(r"needs: \[ci, extras, docs\]", _job("release.yml", "build")), release


def test_the_check_runs_on_every_python_pyproject_lists():
    """CI once ran only the Python uv picked (3.14, from .python-version), so a 3.13-only
    failure could pass it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
    minimum = re.search(r'requires-python = ">=(3\.\d+)"', pyproject)
    assert minimum and listed and listed[0] == minimum.group(1), "classifiers start at the minimum"
    for name in ("collect", "test", "check"):
        job = _job("ci.yml", name)
        matrix = re.search(r"(?m)^\s+python: \[(.*)\]$", job)
        assert matrix, f"ci.yml's {name} job has no python matrix"
        assert re.findall(r'"(3\.\d+)"', matrix.group(1)) == listed, name
    for name in ("collect", "test"):
        job = _job("ci.yml", name)
        assert "UV_PYTHON: ${{ matrix.python }}" in job
        assert "python: ${{ matrix.python }}" in job
    setup = (ROOT / ".github" / "actions" / "check-setup" / "action.yml").read_text("utf-8")
    assert "PYTHON: ${{ inputs.python }}" in setup
    assert 'uv sync --locked --python "$PYTHON"' in setup


def test_workflows_pin_one_effect_commit():
    """The oracle tests, mutation runs and the runtime differential job compare
    against one Effect."""
    pins = {
        path.name: re.findall(r"EFFECT_COMMIT: ([0-9a-f]{40})", path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }
    assert {"ci.yml", "fuzz.yml"} <= {name for name, commits in pins.items() if commits}
    assert len({commit for commits in pins.values() for commit in commits}) == 1, pins


def test_the_fuzz_workflow_compares_fresh_programs_with_node():
    job = _job("fuzz.yml", "runtime-differential")
    assert "python -m runtime_diff --fresh" in job
    assert "PYFECT_EFFECT_REF" in job and "setup-node" in job


def test_ci_runs_the_node_the_recorded_answers_came_from():
    """The Intl, ICU zone and node:path answers were recorded under one Node; under another the
    tests that compare with it skip, which CI fails (tests/_skips.py)."""
    pinned = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    fixtures = ROOT / "tests" / "oracle"
    recorded = {
        "pyfect.date_time._icu_zones.NODE_VERSION": NODE_VERSION,
        "intl_answers.json": json.loads((fixtures / "intl_answers.json").read_text())["node"],
        "node_path_cases.json": json.loads(
            (fixtures / "fixtures" / "node_path_cases.json").read_text()
        )["node"],
    }
    assert recorded == dict.fromkeys(recorded, pinned)
    for path in (".github/actions/check-setup/action.yml", ".github/workflows/fuzz.yml"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "node-version-file: .node-version" in text, path
