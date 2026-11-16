import pyfect as fx
from pyfect.crypto.digest import layer_web_crypto
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.sql import sqlite

# The store ids your app opens: the server keeps only a hash of each.
STORE_IDS = ["main", "notes"]

# Your server's database; this one is empty, so nothing waits.
database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))

stores = fx.run_blocking(
    SqlServer.legacy_stores(STORE_IDS)
    .pipe(fx.provide(layer_web_crypto))
    .pipe(fx.provide(database))
    .or_die()
)
for store in stores:
    match store.state:
        case "ambiguous":
            print(f"decide: {store.store_id!r} of {store.public_key!r}, or {store.other_keys}")
        case "taken":
            print(f"check: {store.store_id!r} of {store.public_key!r} went to another pair")
        case "split":
            print(
                f"a 0.6.5 node wrote {store.store_id!r} of {store.public_key!r} after the upgrade"
            )
        case "pending" | "migrated":
            pass
assert stores == []
