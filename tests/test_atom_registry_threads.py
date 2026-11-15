"""A registry runs on one scheduler and its nodes are not locked, so using it
from another thread while that scheduler runs fails at once with
``RegistryThreadError`` (DOGFOOD pulse #4: ``hydration.dehydrate`` inside
``fx.blocking`` raised ``dictionary changed size during iteration`` on quit).
Effect has no threads; this is pyfect's own rule.

A run's end does not end its registry's work: as in Effect, a node's removal
check runs on a later turn of the scheduler, which after the run is the
background thread (``SyncScheduler.adopt``). Until it has run, the registry is
in use there. Tests that read a registry off-thread once the run is over do so
through ``_run_to_idle``, which waits for that work rather than racing it.
"""

import threading
from collections.abc import Callable

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.exit import is_failure
from pyfect.reactivity import async_result, atom, atom_registry, hydration
from pyfect.reactivity.atom_registry import AtomRegistryService, RegistryThreadError
from pyfect.scheduler import BACKGROUND, SyncScheduler

_counter = atom.make(0)
_count = atom.make(fx.succeed(1)).serializable(
    key="count", schema=async_result.Schema(success=S.Int)
)

# Every public method of the registry, called as another thread would.
_ENTRY_POINTS: dict[str, Callable[[AtomRegistryService], object]] = {
    "check_thread": lambda r: r.check_thread(),
    "get_nodes": lambda r: r.get_nodes(),
    "get": lambda r: r.get(_counter),
    "set": lambda r: r.set(_counter, 1),
    "set_serializable": lambda r: r.set_serializable("count", None),
    "modify": lambda r: r.modify(_counter, lambda n: (n, n + 1)),
    "update": lambda r: r.update(_counter, lambda n: n + 1),
    "refresh": lambda r: r.refresh(_counter),
    "subscribe": lambda r: r.subscribe(_counter, lambda _: None),
    "mount": lambda r: r.mount(_counter),
    "ensure_node": lambda r: r.ensure_node(_counter),
    "create_node": lambda r: r.ensure_node(_counter),
    "invalidate_atom": lambda r: r.invalidate_atom(_counter),
    "reset": lambda r: r.reset(),
    "dispose": lambda r: r.dispose(),
    "fork": lambda r: r.fork(fx.void, fx.Context.empty()),
}

# Called only by the registry's own nodes and scheduled tasks (which run on
# its scheduler), or reading nothing but the atom.
_INTERNAL = {
    "atom_has_ttl",
    "schedule_atom_removal",
    "schedule_node_removal",
    "remove_node",
    "set_node_timeout",
    "remove_node_timeout",
    "sweep_bucket",
    "remove_idle_node",
    "destroy_node",
}


def _off_thread(thunk: Callable[[], object]) -> fx.Effect[object]:
    """The defect of running ``thunk`` on a blocking thread, if any."""
    return (
        fx.blocking(thunk)
        .exit()
        .map(lambda ex: ex.cause.defects[0] if is_failure(ex) and ex.cause.defects else None)
    )


def test_every_public_method_is_an_entry_point_or_internal() -> None:
    public = {
        name
        for name in dir(AtomRegistryService)
        if not name.startswith("_") and callable(getattr(AtomRegistryService, name))
    }
    assert public == set(_ENTRY_POINTS) | _INTERNAL


@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
@testing.live
def test_an_entry_point_called_off_the_scheduler_thread_fails_at_once(name: str):
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    registry.mount(_counter)
    use = _ENTRY_POINTS[name]
    defect = yield from _off_thread(lambda: use(registry))
    assert isinstance(defect, RegistryThreadError)
    assert "(fx.sync, not fx.blocking)" in str(defect)
    assert registry.get(_counter) == 0


@testing.live
def test_dehydrate_inside_blocking_names_the_thread_rule():
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    registry.mount(_count)
    yield from atom_registry.get_result(registry, _count)
    defect = yield from _off_thread(lambda: hydration.dehydrate(registry))
    assert isinstance(defect, RegistryThreadError)
    assert "while its scheduler runs on thread" in str(defect)
    [entry] = yield from fx.sync(lambda: hydration.dehydrate(registry))
    assert entry.key == "count"


def _build_counter_registry(registries: list[AtomRegistryService]) -> fx.Effect[None]:
    @fx.gen
    def build():
        registry = atom_registry.make()
        registries.append(registry)
        registry.mount(_counter)  # schedules the node's removal check
        registry.set(_counter, 3)
        yield from fx.void

    return build


def _settle(registry: AtomRegistryService) -> None:
    """Wait until no task of ``registry``'s scheduler, adopted by the background
    scheduler, is queued or running: each pass waits for a marker queued behind
    them on the background thread, which runs its tasks in order."""
    scheduler = registry.scheduler
    assert isinstance(scheduler, SyncScheduler), "made inside fx.run_blocking"
    while scheduler.driver() is not None:
        passed = threading.Event()
        BACKGROUND.schedule(passed.set)
        assert passed.wait(timeout=10), "the background scheduler is stuck"


def _run_to_idle(
    build: Callable[[list[AtomRegistryService]], fx.Effect[None]],
) -> AtomRegistryService:
    """Run ``build`` with ``fx.run_blocking``, then wait for the work it left
    to the registry's scheduler: the registry it made, idle."""
    registries: list[AtomRegistryService] = []
    fx.run_blocking(build(registries))
    [registry] = registries
    _settle(registry)
    return registry


def _read_on_another_thread(registry: AtomRegistryService) -> int:
    return fx.run_blocking(fx.blocking(lambda: registry.get(_counter)))


def test_a_registry_whose_scheduler_is_not_running_can_be_read_from_any_thread() -> None:
    registry = _run_to_idle(_build_counter_registry)
    assert _read_on_another_thread(registry) == 3


def test_a_removal_check_left_by_a_finished_run_keeps_the_registry_in_use() -> None:
    """The removal check the run scheduled is the registry's work on the
    background thread (Effect runs it on a later tick too), so a read from
    another thread before it has run fails at once; after it, the read works."""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        held.set()
        assert release.wait(timeout=10)

    BACKGROUND.schedule(hold)
    assert held.wait(timeout=10)
    registries: list[AtomRegistryService] = []
    try:
        fx.run_blocking(_build_counter_registry(registries))
        [registry] = registries
        defect = fx.run_blocking(_off_thread(lambda: registry.get(_counter)))
    finally:
        release.set()
    assert isinstance(defect, RegistryThreadError)
    _settle(registry)
    assert _read_on_another_thread(registry) == 3
