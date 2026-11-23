"""DEF-ZHIXU-A-TEST-001 的开发回归。夹具协议，不是真实 Qwen 取消。"""

from __future__ import annotations

import sqlite3
import threading

from tests.conftest import FixtureUpstream, login, make_client, wait_terminal
from tests.test_phase_a import PASSWORD


def _row(settings, request_id: str):
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status, finalized FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    done = conn.execute(
        "SELECT COUNT(*) AS n FROM request_events WHERE request_id = ? AND event = 'done'",
        (request_id,),
    ).fetchone()["n"]
    error = conn.execute(
        "SELECT COUNT(*) AS n FROM request_events WHERE request_id = ? AND event = 'error'",
        (request_id,),
    ).fetchone()["n"]
    message = conn.execute(
        "SELECT status, content FROM messages WHERE request_id = ? AND role = 'assistant'",
        (request_id,),
    ).fetchone()
    conn.close()
    return row, done, error, message


def _send(client, conversation_id: str, content: str):
    sent = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": content},
    )
    return sent


def test_double_cancel_then_resend_eight_times(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["已生成的半句", "不该留下的后半"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_FIXTURE_HOLD="1",
        ZHIXU_UPSTREAM_CONNECT_TIMEOUT="2",
        ZHIXU_UPSTREAM_FIRST_BYTE_TIMEOUT="3",
        ZHIXU_UPSTREAM_TOTAL_TIMEOUT="20",
    )
    try:
        login(client, "cancel_repeat", PASSWORD)
        for index in range(8):
            conv = client.post("/api/conversations", json={"title": f"取消{index}"}).json()["id"]
            sent = _send(client, conv, "普通问题")
            assert sent.status_code == 202, sent.text
            request_id = sent.json()["request_id"]
            deadline_row = None
            for _ in range(160):
                conn = sqlite3.connect(settings.db_path)
                count = conn.execute(
                    "SELECT COUNT(*) FROM request_events WHERE request_id = ? AND event = 'delta'",
                    (request_id,),
                ).fetchone()[0]
                conn.close()
                if count >= 1:
                    deadline_row = count
                    break
                import time

                time.sleep(0.05)
            assert deadline_row, "没有等到第一条增量"
            first = client.post(f"/api/requests/{request_id}/cancel")
            second = client.post(f"/api/requests/{request_id}/cancel")
            assert first.status_code == 200
            assert second.status_code == 200
            wait_terminal(settings, request_id)
            row, done, _error, message = _row(settings, request_id)
            assert row["status"] == "stopped", index
            assert row["finalized"] == 1
            assert done == 1
            assert message["status"] == "stopped"
            assert "已生成的半句" in message["content"]
            assert "不该留下的后半" not in message["content"]
            again = _send(client, conv, "停止后应能再发")
            assert again.status_code == 202, (index, again.status_code, again.text)
    finally:
        client.close()
        upstream.close()


def test_upstream_error_and_cutoff_still_release(tmp_path, monkeypatch):
    upstream = FixtureUpstream(mode="status", status=500)
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_UPSTREAM_RETRY_DELAYS="0,0",
    )
    try:
        login(client, "cancel_error", PASSWORD)
        conv = client.post("/api/conversations", json={"title": "上游错误"}).json()["id"]
        sent = _send(client, conv, "会失败的问题")
        assert sent.status_code == 202, sent.text
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        row, done, errors, message = _row(settings, request_id)
        assert row["status"] == "failed"
        assert row["finalized"] == 1
        assert errors == 1
        assert done == 0
        assert message["status"] == "failed"
        again = _send(client, conv, "失败后应能再发")
        assert again.status_code == 202, again.text
    finally:
        client.close()
        upstream.close()

    upstream = FixtureUpstream(chunks=["半句后断开"], mode="cutoff")
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
    )
    try:
        login(client, "cancel_cutoff", PASSWORD)
        conv = client.post("/api/conversations", json={"title": "中途断开"}).json()["id"]
        sent = _send(client, conv, "会断开的问题")
        assert sent.status_code == 202, sent.text
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        row, done, errors, message = _row(settings, request_id)
        assert row["status"] == "failed"
        assert row["finalized"] == 1
        assert row["status"] != "cancel_requested"
        assert errors == 1
        assert done == 0
        assert "半句后断开" in message["content"]
        again = _send(client, conv, "断开后应能再发")
        assert again.status_code == 202, again.text
    finally:
        client.close()
        upstream.close()


def test_concurrent_cancels_do_not_stick(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["已生成的半句", "不该留下的后半"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_FIXTURE_HOLD="1",
    )
    try:
        login(client, "cancel_parallel", PASSWORD)
        for index in range(4):
            conv = client.post("/api/conversations", json={"title": f"并发{index}"}).json()["id"]
            sent = _send(client, conv, "普通问题")
            request_id = sent.json()["request_id"]
            for _ in range(160):
                conn = sqlite3.connect(settings.db_path)
                count = conn.execute(
                    "SELECT COUNT(*) FROM request_events WHERE request_id = ? AND event = 'delta'",
                    (request_id,),
                ).fetchone()[0]
                conn.close()
                if count >= 1:
                    break
                import time

                time.sleep(0.05)
            errors = []

            def once():
                try:
                    response = client.post(f"/api/requests/{request_id}/cancel")
                    if response.status_code != 200:
                        errors.append(response.status_code)
                except Exception as exc:  # 记录夹具线程里的异常，不吞掉
                    errors.append(type(exc).__name__)

            threads = [threading.Thread(target=once) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert errors == []
            wait_terminal(settings, request_id)
            row, done, _error, message = _row(settings, request_id)
            assert row["status"] == "stopped", index
            assert row["finalized"] == 1
            assert done == 1
            assert "已生成的半句" in message["content"]
            again = _send(client, conv, "并发停止后应能再发")
            assert again.status_code == 202, again.text
    finally:
        client.close()
        upstream.close()
