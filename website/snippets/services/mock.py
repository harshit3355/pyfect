from typing import Protocol

import pyfect as fx
from pyfect import layer


class Mailer(Protocol):
    def send(self, to: str) -> fx.Effect[None]: ...
    def sent(self) -> fx.Effect[int]: ...


class Mail(fx.Tag[Mailer], key="Mail"): ...


@fx.fn
def notify(to: str):
    mailer = yield from Mail()
    yield from mailer.send(to)
    return to


def send(to: str) -> fx.Effect[None]:
    return fx.void


# Only `send` is mocked: calling `sent` would die with UnimplementedError.
mocked = layer.mock(Mail, send=send)
assert fx.run_blocking(notify("ada").pipe(fx.provide(mocked))) == "ada"

# pyright doesn't check the member names, so a misspelt one leaves `send` unmocked.
# The defect names the member it may be a typo of.
misspelt = layer.mock(Mail, sned=send)
exit = fx.run_blocking_exit(notify("ada").pipe(fx.provide(misspelt)))
assert isinstance(exit, fx.Failure)
assert str(exit.cause.defects[0]) == (
    'Mail: Unimplemented method "send"; layer.mock was given "sned": a typo?'
)
