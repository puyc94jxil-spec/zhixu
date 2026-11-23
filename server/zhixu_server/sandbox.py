"""非特权、无网络、目录受限的解析子进程。

做不到探针要求时 fail closed，不退回工作线程或本进程解析。
探针通过只说明 DEV 环境里隔离原语可用，不等于安全验收已通过。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from zhixu_server.logutil import log_event

_PROBE_LOCK = threading.Lock()
_PROBE: dict | None = None
_ACTIVE: dict[str, subprocess.Popen] = {}
_ACTIVE_LOCK = threading.Lock()
_WALL_SECONDS = 120
_EXPAND_FACTOR = 10


class IsolationError(RuntimeError):
    pass


class ParseFailed(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def bwrap_path() -> str | None:
    return shutil.which("bwrap")


def _command(work: Path, sentinel: Path | None = None) -> list[str]:
    del sentinel
    bwrap = bwrap_path()
    if not bwrap:
        raise IsolationError("bwrap_missing")
    pkg = Path(__file__).resolve().parent
    cmd = [
        bwrap,
        "--unshare-user",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--uid",
        "65534",
        "--gid",
        "65534",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
    ]
    if Path("/lib64").is_dir():
        cmd.extend(["--ro-bind", "/lib64", "/lib64"])
    cmd.extend(
        [
            "--tmpfs",
            "/tmp",
            "--proc",
            "/proc",
            "--ro-bind",
            str(pkg),
            "/pkg/zhixu_server",
            "--ro-bind",
            str(work),
            "/work",
            "--chdir",
            "/work",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "PYTHONPATH",
            "/pkg",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "LANG",
            "C.UTF-8",
        ]
    )
    return cmd


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(proc.pid, 9)
        proc.wait(timeout=5)
        raise ParseFailed("timeout") from exc
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def probe(force: bool = False) -> dict:
    """返回隔离探针结果。不访问业务内网地址。"""
    global _PROBE
    with _PROBE_LOCK:
        if _PROBE is not None and not force:
            return _PROBE
        result = {
            "ready": False,
            "reason": "unprobed",
            "uid": None,
            "network": None,
            "sentinel_blocked": None,
        }
        if not bwrap_path():
            result["reason"] = "bwrap_missing"
            _PROBE = result
            log_event("isolation_unavailable", reason="bwrap_missing")
            return result
        work = Path(tempfile.mkdtemp(prefix="zhixu-probe-"))
        sentinel = Path(tempfile.mkdtemp(prefix="zhixu-secret-")) / "secret.txt"
        try:
            (work / "input.bin").write_text("probe", encoding="utf-8")
            os.chmod(work / "input.bin", 0o644)
            sentinel.write_text("SECRET", encoding="utf-8")
            os.chmod(sentinel, 0o600)
            code = (
                "import os,socket\n"
                "print('UID', os.geteuid())\n"
                "print('IN', open('input.bin',encoding='utf-8').read())\n"
                "try:\n"
                " socket.socket().connect(('203.0.113.1', 9))\n"
                " print('NET', 'ok')\n"
                "except OSError as e:\n"
                " print('NET', 'fail', e.errno)\n"
                f"p={str(sentinel)!r}\n"
                "try:\n"
                " open(p).read(); print('SENTINEL', 'leak')\n"
                "except Exception:\n"
                " print('SENTINEL', 'blocked')\n"
            )
            cmd = _command(work)
            cmd.extend(["--", "python3", "-c", code])
            started = time.monotonic()
            completed = _run(cmd, 30)
            text = completed.stdout.decode("utf-8", errors="replace")
            uid = None
            for line in text.splitlines():
                if line.startswith("UID "):
                    uid = line.split()[1]
            net_fail = "NET fail" in text
            sentinel_blocked = "SENTINEL blocked" in text
            input_ok = "IN probe" in text
            ready = (
                completed.returncode == 0
                and uid not in {None, "0"}
                and net_fail
                and sentinel_blocked
                and input_ok
            )
            result = {
                "ready": ready,
                "reason": "ok" if ready else "probe_failed",
                "uid": uid,
                "network": "unreachable" if net_fail else "unexpected",
                "sentinel_blocked": sentinel_blocked,
                "returncode": completed.returncode,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001  探针失败必须 fail closed
            result = {"ready": False, "reason": type(exc).__name__, "uid": None}
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(sentinel.parent, ignore_errors=True)
        _PROBE = result
        log_event(
            "isolation_probe",
            ready=result["ready"],
            reason=result.get("reason"),
            uid=result.get("uid"),
        )
        return result


def cancel_extract(job_id: str) -> None:
    with _ACTIVE_LOCK:
        proc = _ACTIVE.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            return


def extract_text(source: Path, size: int, job_id: str | None = None) -> str:
    """在隔离子进程中读取原文。失败时抛出 ParseFailed，调用方不得改在本进程解析。"""
    if not probe().get("ready"):
        raise ParseFailed("isolation_unavailable")
    work = Path(tempfile.mkdtemp(prefix="zhixu-parse-"))
    try:
        target = work / "input.bin"
        shutil.copyfile(source, target)
        os.chmod(target, 0o644)
        os.chmod(work, 0o755)
        cmd = _command(work)
        cmd.extend(["--", "python3", "-m", "zhixu_server.parser_child"])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        if job_id:
            with _ACTIVE_LOCK:
                _ACTIVE[job_id] = proc
        try:
            out, err = proc.communicate(timeout=_WALL_SECONDS)
        except subprocess.TimeoutExpired as exc:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=5)
            raise ParseFailed("timeout") from exc
        finally:
            if job_id:
                with _ACTIVE_LOCK:
                    _ACTIVE.pop(job_id, None)
        completed = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        stdout = completed.stdout or b""
        limit = max(size * _EXPAND_FACTOR, 1)
        if len(stdout) > limit:
            raise ParseFailed("expand_limit")
        err = (completed.stderr or b"").decode("utf-8", errors="replace")[:80]
        if completed.returncode != 0:
            if "ERR empty" in err:
                raise ParseFailed("empty")
            if "ERR binary" in err:
                raise ParseFailed("binary")
            if "ERR limits" in err:
                raise ParseFailed("limits")
            raise ParseFailed("parse_failed")
        return stdout.decode("utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
