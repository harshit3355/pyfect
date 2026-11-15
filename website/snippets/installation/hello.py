import pyfect as fx

hello = fx.succeed("world").map(lambda name: f"Hello, {name}!")

message = fx.run_blocking(hello)
assert message == "Hello, world!"
print(message)
