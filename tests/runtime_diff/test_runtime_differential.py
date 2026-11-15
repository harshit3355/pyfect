"""pyfect's runtime answers the checked-in programs as Effect 4.1.2 does.

``corpus.json`` holds generated cases (program.py: a program and the
``MaxOpsBeforeYield`` it runs under) with what effect_interpreter.ts answered for
each under Node: the exit, its cause's shape and every event in order. Each
replays here without Node. Grow or refresh it
with ``python -m runtime_diff --write N`` / ``--refresh`` (from ``tests/``);
the fuzz workflow compares freshly generated programs against Node.
"""

import re

import pytest

from . import generate, oracle, program

_CORPUS = oracle.read_corpus()


@pytest.mark.parametrize(
    ("case", "effect"), _CORPUS, ids=[f"program-{i}" for i in range(len(_CORPUS))]
)
def test_pyfect_answers_as_effect_does(case: program.Case, effect: program.Json):
    found = oracle.difference(case, effect)
    assert found is None, found


def test_the_corpus_runs_out_of_budget():
    """Most cases run under a budget small enough to make fibers yield."""
    small = [budget for (_, budget), _ in _CORPUS if budget <= 200]
    assert len(small) * 2 > len(_CORPUS), "add cases (--write)"


def test_the_corpus_uses_every_node():
    """A node added to the language is compared with Effect in every run."""
    used = generate.ops([program.to_json(expr) for (expr, _), _ in _CORPUS])
    assert set(program.NODES) - used == set(), "regenerate corpus.json (--write)"


def test_the_corpus_runs_every_node_at_every_swept_budget():
    """An op count one off from Effect's shows at the one budget where that op is the
    last before a yield, which fresh programs at random budgets hit by luck: every node
    runs, in a probed program (generate.probe), at each of ``SWEEP_BUDGETS``."""
    swept: dict[str, set[int]] = {name: set() for name in program.NODES}
    for (expr, budget), _ in _CORPUS:
        for name in generate.ops(program.to_json(expr)):
            swept[name].add(budget)
    wanted = set(generate.SWEEP_BUDGETS)
    missing = {
        name: sorted(wanted - budgets) for name, budgets in swept.items() if wanted - budgets
    }
    assert missing == {}, "add the sweep to corpus.json (--sweep)"


def test_the_effect_interpreter_handles_every_node():
    """The two interpreters cover the same language."""
    source = oracle.INTERPRETER.read_text(encoding="utf-8")
    handled = set(re.findall(r'case "([A-Z]\w*)"', source))
    assert set(program.NODES) - {"Resource"} == handled


def test_a_nested_program_strategy_has_a_short_repr():
    """Hypothesis prints a strategy's repr when it re-encodes a drawn value, and
    ``st.recursive`` nests ``_extend`` once per doubling of ``max_leaves``: a level
    that repeated its children's repr made the fuzz job's reports grow to gigabytes."""
    nested = generate._extend(generate._extend(generate._extend(generate._LEAVES)))  # pyright: ignore[reportPrivateUsage]
    assert len(repr(nested)) < 20_000
