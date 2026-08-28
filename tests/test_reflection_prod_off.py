"""SE-04 -- gRPC reflection is enabled only in development.

Reflection lets `grpcurl list` enumerate the whole service schema without the
proto file. That is a convenience in dev and an information leak in prod, so
`register_all_servicers` gates `enable_server_reflection` behind
`settings.environment == "development"`. This asserts the gate structurally
(no servicer instantiation, no running server needed): the reflection call
exists, the development guard exists, and the call is nested under it.
"""

from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "src" / "grpc_server" / "server.py"


def test_reflection_is_gated_by_development_environment() -> None:
    src = SERVER.read_text(encoding="utf-8")

    assert "enable_server_reflection" in src, "reflection setup vanished"
    guard = 'if settings.environment == "development":'
    assert guard in src, "the development guard on reflection is gone"

    # Every reflection-enabling call must be deeply indented -- i.e. nested
    # inside the guard's `try` block, never at module or function top level.
    for line in src.splitlines():
        if "enable_server_reflection" in line:
            indent = len(line) - len(line.lstrip(" "))
            assert indent >= 12, (
                "enable_server_reflection is not nested under the development "
                f"guard (indent={indent}): {line.strip()}"
            )
