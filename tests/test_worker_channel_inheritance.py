"""A process reads worker messages (pickles) only from the parent that started it.

The channel's descriptor number travels in ``PYFECT_WORKER_FD``. A worker that started a
process before reading it passed the variable on, and that grandchild, were it a pyfect
worker too, would have unpickled whatever its own descriptor of that number was. The parent
now also names itself (``PYFECT_WORKER_PARENT``), and a process whose parent is another
ignores the channel.
"""

import os
import socket
import subprocess
import sys

_PROBE = "from pyfect.workers._process import current_parent; print(current_parent() is None)"


def _is_ignored(parent_pid: str | None) -> bool:
    ours, theirs = socket.socketpair()
    with ours, theirs:
        env = {**os.environ, "PYFECT_WORKER_FD": str(theirs.fileno())}
        env.pop("PYFECT_WORKER_PARENT", None)
        if parent_pid is not None:
            env["PYFECT_WORKER_PARENT"] = parent_pid
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            pass_fds=(theirs.fileno(),),
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    return result.stdout.strip() == "True"


def test_a_channel_named_by_another_parent_is_ignored():
    assert _is_ignored(None)
    assert _is_ignored(str(os.getpid() + 1))


def test_the_channel_from_this_parent_is_read():
    assert not _is_ignored(str(os.getpid()))


_INHERITS = (
    "import os; from pyfect.workers._process import current_parent; "
    "port = current_parent(); print(os.get_inheritable(int(os.environ.get('FD', '-1'))))"
)


def test_processes_the_worker_starts_do_not_inherit_the_channel():
    # pass_fds leaves the channel inheritable in the worker; a process it starts with
    # close_fds off (pyfect.process with additional_fds) would get it.
    ours, theirs = socket.socketpair()
    with ours, theirs:
        fd = str(theirs.fileno())
        env = {**os.environ, "PYFECT_WORKER_FD": fd, "FD": fd}
        env["PYFECT_WORKER_PARENT"] = str(os.getpid())
        result = subprocess.run(
            [sys.executable, "-c", _INHERITS],
            pass_fds=(theirs.fileno(),),
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    assert result.stdout.strip() == "False"
