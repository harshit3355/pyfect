"""An event log server refuses a public key or store id that is not
well-formed Unicode (holds a lone surrogate, which a client can send as a
JSON ``"\\ud800"``): such text has no UTF-8 of its own, so it would share
keys, bindings and signatures with the text holding U+FFFD in its place.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as E
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import StoreIdSchema
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_session_auth import SessionAuthPayload, sign_session_auth_payload
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test


def _client():
    storage = yield from E.make_storage_memory
    handlers = E.layer_rpc_handlers.pipe(fx.layer.provide(fx.layer.succeed(E.Storage, storage)))
    return (
        yield from rpc_test.make_client(E.EventLogEncryptedServerRpcs).pipe(fx.provide(handlers))
    )


def _authenticate(identity: IdentityService, hello: M.HelloResponse):
    material = yield from make_get_identity_root_secret_material()(identity)
    signature = yield from sign_session_auth_payload(
        SessionAuthPayload(
            remote_id=hello.remote_id,
            challenge=hello.challenge,
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
        ),
        reveal(material.signing_private_key),
    )
    return M.Authenticate(
        public_key=identity.public_key,
        signing_public_key=material.signing_public_key,
        signature=signature,
        algorithm="Ed25519",
    )


@testing.effect
def test_a_public_key_with_a_lone_surrogate_does_not_authenticate():
    def body():
        client = yield from _client()
        identity = yield from L.make_identity
        ill_formed = IdentityService(identity.public_key + "\ud800", identity.private_key)
        hello = yield from client.hello()
        error = yield from client.authenticate((yield from _authenticate(ill_formed, hello))).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        assert "well-formed" in error.message

        # The same root secret under its well-formed key still authenticates.
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate(identity, hello)))

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer_subtle))


@pytest.mark.parametrize("store_id", ["notes\ud800", "\udc00", "\ud83d"])
def test_a_store_id_with_a_lone_surrogate_does_not_decode(store_id: str) -> None:
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(StoreIdSchema)(store_id)
    payload = {"publicKey": "pk", "storeId": store_id, "startSequence": 0}
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(cast("Any", M.ChangesRpc.payload_schema))(payload)


def test_a_well_formed_store_id_decodes() -> None:
    for store_id in ["notes", "notes\ufffd", "\U0001f600", ""]:
        assert S.decode_unknown_sync(StoreIdSchema)(store_id) == store_id
