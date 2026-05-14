"""Jupyter kernel lifecycle wrapper.

We use ``jupyter_client.KernelManager`` so that students get the full IPython
display protocol (matplotlib inline PNGs, pandas HTML tables, traceback rendering)
without us having to reimplement it.

The manager exposes a synchronous ``execute()`` method that gathers all output
messages until the kernel becomes idle (or the timeout fires) and returns
an ``ExecutionResult``.
"""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass, field
from typing import Any

from jupyter_client.manager import KernelManager

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Captured outputs of a single kernel execution."""

    status: str = "ok"  # "ok" | "error" | "timeout" | "interrupted"
    stdout: str = ""
    stderr: str = ""
    error_name: str = ""
    error_value: str = ""
    traceback: list[str] = field(default_factory=list)
    images_png: list[bytes] = field(default_factory=list)  # base64-decoded PNG bytes
    html_blobs: list[str] = field(default_factory=list)
    text_plain: list[str] = field(default_factory=list)
    execute_reply: dict[str, Any] | None = None


class KernelSession:
    """Owns a single IPython kernel for the lifetime of one chapter session."""

    def __init__(self) -> None:
        self._mgr: KernelManager | None = None
        self._client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._mgr is not None:
            return
        self._mgr = KernelManager(kernel_name="python3")
        self._mgr.start_kernel()
        self._client = self._mgr.client()
        self._client.start_channels()
        self._client.wait_for_ready(timeout=30)
        self._warmup()

    def _warmup(self) -> None:
        """Run a tiny no-op + matplotlib setup so the kernel is fully ready.

        Without this, the first ``execute()`` after start/restart can be
        slow or behave oddly (matplotlib backend not configured, IPython
        display hooks not yet initialised). The student submitting an
        Exercise before pressing Run on the Sample would otherwise hit
        this cold-start path and could get a spurious Incorrect.
        """
        self.execute(
            # `pass` warms the IPython execute pipeline.
            "pass\n"
            "import matplotlib\n"
            "try:\n"
            "    get_ipython().run_line_magic('matplotlib', 'inline')\n"
            "except Exception:\n"
            "    matplotlib.use('Agg')\n",
            timeout=30,
            silent=True,
        )

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                self._client.stop_channels()
            except Exception:  # noqa: BLE001
                log.exception("error stopping kernel channels")
            self._client = None
        if self._mgr is not None:
            try:
                self._mgr.shutdown_kernel(now=True)
            except Exception:  # noqa: BLE001
                log.exception("error shutting down kernel")
            self._mgr = None

    def restart(self) -> None:
        if self._mgr is None:
            self.start()
            return
        self._mgr.restart_kernel(now=True)
        # rebuild client after restart
        self._client.stop_channels()
        self._client = self._mgr.client()
        self._client.start_channels()
        self._client.wait_for_ready(timeout=30)
        # The first ``execute()`` on a freshly-restarted kernel is unreliable
        # without this — see ``_warmup`` docstring.
        self._warmup()

    def interrupt(self) -> None:
        if self._mgr is None:
            return
        try:
            self._mgr.interrupt_kernel()
        except Exception:  # noqa: BLE001
            log.exception("interrupt_kernel failed")

    @property
    def alive(self) -> bool:
        return self._mgr is not None and self._mgr.is_alive()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(
        self,
        code: str,
        *,
        timeout: float = 10.0,
        silent: bool = False,
    ) -> ExecutionResult:
        """Run ``code`` and collect outputs until the kernel becomes idle.

        ``timeout`` is a wall-clock budget; if exceeded we interrupt the kernel
        and return ``status='timeout'`` plus whatever output was captured so far.
        """
        if self._client is None:
            raise RuntimeError("kernel not started")

        result = ExecutionResult()
        msg_id = self._client.execute(code, silent=silent, store_history=not silent)

        import time

        deadline = time.monotonic() + timeout
        # Drain iopub until idle (or timeout).
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.interrupt()
                result.status = "timeout"
                result.stderr += f"\n[実行が {timeout:.0f} 秒を超えたため中断しました]"
                break
            try:
                msg = self._client.get_iopub_msg(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            parent = msg.get("parent_header", {})
            if parent.get("msg_id") != msg_id:
                continue  # output from earlier execution
            mtype = msg["msg_type"]
            content = msg["content"]
            if mtype == "stream":
                if content.get("name") == "stderr":
                    result.stderr += content.get("text", "")
                else:
                    result.stdout += content.get("text", "")
            elif mtype in ("display_data", "execute_result"):
                data = content.get("data", {})
                if "image/png" in data:
                    import base64

                    try:
                        result.images_png.append(base64.b64decode(data["image/png"]))
                    except Exception:  # noqa: BLE001
                        log.exception("failed to decode display image")
                if "text/html" in data:
                    result.html_blobs.append(data["text/html"])
                if "text/plain" in data:
                    result.text_plain.append(data["text/plain"])
            elif mtype == "error":
                result.status = "error"
                result.error_name = content.get("ename", "")
                result.error_value = content.get("evalue", "")
                result.traceback = list(content.get("traceback", []))
            elif mtype == "status" and content.get("execution_state") == "idle":
                break

        # Try to capture the execute_reply (non-blocking) for richer info.
        try:
            reply = self._client.get_shell_msg(timeout=1.0)
            result.execute_reply = reply.get("content", {})
            if reply["content"].get("status") == "error" and result.status == "ok":
                result.status = "error"
                result.error_name = reply["content"].get("ename", "")
                result.error_value = reply["content"].get("evalue", "")
                result.traceback = list(reply["content"].get("traceback", []))
        except queue.Empty:
            pass
        return result

    def evaluate_expression(self, expr: str, *, timeout: float = 5.0) -> tuple[bool, str]:
        """Evaluate a boolean Python expression in the kernel namespace.

        Returns ``(passed, repr_of_value_or_error)``. Used by the grading judge
        for ``namespace_check`` asserts. The expression must not have side effects.
        """
        sentinel = "__study_judge_result__"
        code = f"{sentinel} = bool({expr})\nprint(repr({sentinel}))"
        res = self.execute(code, timeout=timeout, silent=True)
        if res.status != "ok":
            return False, (res.error_value or res.stderr or res.status).strip()
        out = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
        return out == "True", out
