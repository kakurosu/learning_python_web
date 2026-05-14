"""Smoke tests for KernelSession.

These spin up a real IPython kernel; if that's unavailable on the host, we skip.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def kernel():
    pytest.importorskip("jupyter_client")
    pytest.importorskip("ipykernel")
    from app.kernel.manager import KernelSession

    k = KernelSession()
    try:
        k.start()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"kernel not available: {e}")
    yield k
    k.shutdown()


@pytest.mark.kernel
def test_simple_print(kernel) -> None:
    res = kernel.execute('print("hi")', timeout=10)
    assert res.status == "ok"
    assert "hi" in res.stdout


@pytest.mark.kernel
def test_runtime_error(kernel) -> None:
    res = kernel.execute("1/0", timeout=10)
    assert res.status == "error"
    assert "ZeroDivisionError" in res.error_name


@pytest.mark.kernel
def test_namespace_persistence(kernel) -> None:
    kernel.execute("a = 7", timeout=5)
    res = kernel.execute("print(a * 2)", timeout=5)
    assert res.status == "ok"
    assert "14" in res.stdout


@pytest.mark.kernel
def test_evaluate_expression(kernel) -> None:
    kernel.execute("x = 42", timeout=5)
    passed, _ = kernel.evaluate_expression("x == 42")
    assert passed
    passed2, _ = kernel.evaluate_expression("x == 0")
    assert not passed2


@pytest.mark.kernel
def test_timeout_interrupt(kernel) -> None:
    res = kernel.execute("import time\ntime.sleep(30)", timeout=1.0)
    assert res.status in ("timeout", "interrupted", "error")
