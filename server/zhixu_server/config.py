"""运行配置只从环境变量读取。

这里不写模型地址、模型名或密钥的默认值。未配置时上游模式为 unconfigured，
调用会失败，不会改走演示文案。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    objects_dir: Path
    log_path: Path
    allowed_origins: tuple[str, ...]
    cookie_secure: bool
    session_ttl_hours: int
    # live：真实上游；fixture：测试夹具；unconfigured：拒绝生成
    upstream_mode: str
    model_base_url: str
    model_name: str
    model_api_key: str
    connect_timeout: float
    first_byte_timeout: float
    total_timeout: float
    retry_delays: tuple[float, ...]
    # 仅 fixture 模式生效，live 模式忽略，避免和生产混用
    fixture_hold: bool
    web_dir: Path
    prototype_dir: Path
    host: str
    port: int


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("ZHIXU_DATA_DIR", "./data")).expanduser().resolve()
    origins = tuple(
        item.strip().rstrip("/")
        for item in os.environ.get(
            "ZHIXU_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
        ).split(",")
        if item.strip()
    )
    url = os.environ.get("ZHIXU_MODEL_BASE_URL", "").strip().rstrip("/")
    name = os.environ.get("ZHIXU_MODEL_NAME", "").strip()
    key = os.environ.get("ZHIXU_MODEL_API_KEY", "")
    mode = os.environ.get("ZHIXU_UPSTREAM_MODE", "").strip().lower()
    if mode not in {"live", "fixture", "unconfigured"}:
        mode = "live" if url and name else "unconfigured"
    if mode == "live" and (not url or not name):
        mode = "unconfigured"
    if mode == "fixture" and not url:
        mode = "unconfigured"
    delays_raw = os.environ.get("ZHIXU_UPSTREAM_RETRY_DELAYS", "0.5,1.5")
    delays = tuple(float(part) for part in delays_raw.split(",") if part.strip())
    if len(delays) < 2:
        delays = (0.5, 1.5)
    root = Path(__file__).resolve().parents[2]
    hold = _flag("ZHIXU_FIXTURE_HOLD") and mode == "fixture"
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "zhixu.db",
        objects_dir=data_dir / "objects",
        log_path=data_dir / "logs" / "zhixu.log",
        allowed_origins=origins,
        cookie_secure=_flag("ZHIXU_COOKIE_SECURE"),
        session_ttl_hours=int(os.environ.get("ZHIXU_SESSION_TTL_HOURS", "12")),
        upstream_mode=mode,
        model_base_url=url,
        model_name=name,
        model_api_key=key,
        connect_timeout=_float("ZHIXU_UPSTREAM_CONNECT_TIMEOUT", 15),
        first_byte_timeout=_float("ZHIXU_UPSTREAM_FIRST_BYTE_TIMEOUT", 15),
        total_timeout=_float("ZHIXU_UPSTREAM_TOTAL_TIMEOUT", 120),
        retry_delays=delays[:2],
        fixture_hold=hold,
        web_dir=root / "web",
        prototype_dir=root / "prototype",
        host=os.environ.get("ZHIXU_HOST", "127.0.0.1"),
        port=int(os.environ.get("ZHIXU_PORT", "8000")),
    )
