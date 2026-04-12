"""
行为调优配置层 — TuningConfig 及其子数据类 + load_tuning() / get_tuning()

从 tuning.yaml 加载所有微服务的行为参数（超时、阈值、批处理等），
每个字段均可通过同名环境变量覆盖。

环境变量命名规则: 与 YAML key 对应，大写下划线风格。
  例如: ORCH_CIRCUIT_FAIL_THRESHOLD, VOICE_TTS_CONNECT_TIMEOUT_SEC
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .config_base import (
    TUNING_PATH,
    _env_int,
    _env_str,
    _read_bool,
)


# ===================== 子数据类 =====================


@dataclass
class ServicesTuning:
    """微服务端口与地址配置。"""

    gateway_port: int = 18080
    orchestrator_port: int = 18081
    memory_service_port: int = 18082
    agent_service_port: int = 18083
    voice_service_port: int = 18084
    orchestrator_url: str = "http://localhost:18081"
    memory_service_url: str = "http://localhost:18082"
    agent_service_url: str = "http://localhost:18083"
    voice_service_url: str = "http://localhost:18084"


@dataclass
class OrchestratorTuning:
    """编排器行为调优参数。"""

    llm_executor_workers: int = 4
    memory_timeout_sec: float = 8.0
    memory_retrieve_timeout_sec: float = 8.0
    memory_store_timeout_sec: float = 1.8
    memory_batch_timeout_sec: float = 10.0
    agent_timeout_sec: float = 180.0
    voice_timeout_sec: float = 60.0

    # 全局入口限流（令牌桶）
    max_requests_per_second: float = 8.0
    burst_size: int = 16

    voice_async_batch_enabled: bool = True
    voice_batch_max_size: int = 8
    voice_batch_collect_window_ms: int = 8
    voice_batch_result_wait_sec: float = 1.2
    voice_batch_congested_queue_size: int = 12
    voice_batch_result_wait_sec_congested: float = 0.4
    voice_hit_priority_direct_enabled: bool = True
    voice_hit_priority_direct_timeout_sec: float = 8.0

    circuit_fail_threshold: int = 3
    circuit_cooldown_sec: float = 30.0
    pending_memory_queue_size: int = 24


@dataclass
class VoiceTuning:
    """语音/TTS 管道调优参数。"""

    connect_timeout_sec: int = 5
    read_timeout_sec: int = 30
    streaming_mode: int = 3          # 0=off, 2=simple, 3=full
    parallel_infer: bool = False
    min_chunk_length: int = 8
    overlap_length: int = 1
    text_split_method: str = "cut1"

    buffered_fallback_enabled: bool = True
    system_tts_fallback_enabled: bool = True

    cpp_accel_lib: str = ""

    wav_output_dir: str = "data/temp"
    wav_cleanup_enabled: bool = True
    wav_cleanup_interval_sec: float = 120.0
    wav_ttl_sec: float = 1800.0


@dataclass
class ExpressionTuning:
    """表情/Avatar 系统调优参数。"""

    # ExpressionOrchestrator 时间线调度
    auto_reset_sec: float = 2.4
    min_timer_gap_ms: int = 120
    timeline_play_motion: bool = False

    # ExpressionManager / expression.py 加权情感分析
    min_segment_sec: float = 0.30
    min_hold_sec: float = 0.55
    switch_margin: float = 0.10
    continuity_bias: float = 0.12
    smooth_window_sec: float = 0.55
    neutral_tail_sec: float = 0.26


@dataclass
class GatewayTuning:
    """网关调优参数。"""

    chat_timeout_sec: float = 60.0
    api_key: str = ""


@dataclass
class ClientTuning:
    """客户端(ServiceClient)调优参数。"""

    user_id: str = "local-gui"
    request_timeout_sec: int = 30


# ===================== TuningConfig 主类 =====================


@dataclass
class TuningConfig:
    """
    行为调优配置的唯一真相来源。

    从 tuning.yaml 加载，每个字段都可以被同名环境变量覆盖。
    """

    services: ServicesTuning = field(default_factory=ServicesTuning)
    orchestrator: OrchestratorTuning = field(default_factory=OrchestratorTuning)
    voice: VoiceTuning = field(default_factory=VoiceTuning)
    expression: ExpressionTuning = field(default_factory=ExpressionTuning)
    gateway: GatewayTuning = field(default_factory=GatewayTuning)
    client: ClientTuning = field(default_factory=ClientTuning)

    @classmethod
    def from_yaml(cls, path: Optional[str] = None) -> "TuningConfig":
        """从 tuning.yaml 加载配置，环境变量覆盖同名项。"""
        t_path = path or TUNING_PATH

        # 加载 YAML 默认值
        defaults: dict = {}
        if os.path.exists(t_path):
            with open(t_path, encoding="utf-8") as f:
                defaults = yaml.safe_load(f) or {}

        def _get(d: dict, key: str, default=None):
            """安全获取字典值（单层查找）。"""
            if not isinstance(d, dict):
                return default
            return d.get(key, default)

        svc_raw = defaults.get("services", {}) or {}
        orch_raw = defaults.get("orchestrator", {}) or {}
        voice_raw = defaults.get("voice", {}) or {}
        expr_raw = defaults.get("expression", {}) or {}
        gw_raw = defaults.get("gateway", {}) or {}
        cli_raw = defaults.get("client", {}) or {}

        return cls(
            services=ServicesTuning(
                gateway_port=_env_int("GATEWAY_PORT", _get(svc_raw, "gateway_port", 18080)),
                orchestrator_port=_env_int("ORCHESTRATOR_PORT", _get(svc_raw, "orchestrator_port", 18081)),
                memory_service_port=_env_int("MEMORY_SERVICE_PORT", _get(svc_raw, "memory_service_port", 18082)),
                agent_service_port=_env_int("AGENT_SERVICE_PORT", _get(svc_raw, "agent_service_port", 18083)),
                voice_service_port=_env_int("VOICE_SERVICE_PORT", _get(svc_raw, "voice_service_port", 18084)),
                orchestrator_url=_env_str("ORCHESTRATOR_URL", _get(svc_raw, "orchestrator_url", "http://localhost:18081")),
                memory_service_url=_env_str("MEMORY_SERVICE_URL", _get(svc_raw, "memory_service_url", "http://localhost:18082")),
                agent_service_url=_env_str("AGENT_SERVICE_URL", _get(svc_raw, "agent_service_url", "http://localhost:18083")),
                voice_service_url=_env_str("VOICE_SERVICE_URL", _get(svc_raw, "voice_service_url", "http://localhost:18084")),
            ),
            orchestrator=OrchestratorTuning(
                llm_executor_workers=max(1, _env_int("ORCH_LLM_EXECUTOR_WORKERS", _get(orch_raw, "llm_executor_workers", 4))),
                memory_timeout_sec=float(_env_str("ORCH_MEMORY_TIMEOUT_SEC", _get(orch_raw, "memory_timeout_sec", 8.0))),
                memory_retrieve_timeout_sec=float(_env_str("ORCH_MEMORY_RETRIEVAL_TIMEOUT_SEC", _get(orch_raw, "memory_retrieve_timeout_sec", 8.0))),
                memory_store_timeout_sec=float(_env_str("ORCH_MEMORY_STORE_TIMEOUT_SEC", _get(orch_raw, "memory_store_timeout_sec", 1.8))),
                memory_batch_timeout_sec=float(_env_str("ORCH_MEMORY_BATCH_TIMEOUT_SEC", _get(orch_raw, "memory_batch_timeout_sec", 10.0))),
                agent_timeout_sec=float(_env_str("ORCH_AGENT_TIMEOUT_SEC", _get(orch_raw, "agent_timeout_sec", 180.0))),
                voice_timeout_sec=float(_env_str("ORCH_VOICE_TIMEOUT_SEC", _get(orch_raw, "voice_timeout_sec", 60.0))),
                max_requests_per_second=max(0.1, float(_env_str("ORCH_MAX_REQUESTS_PER_SECOND", _get(orch_raw, "max_requests_per_second", 8.0)))),
                burst_size=max(1, _env_int("ORCH_BURST_SIZE", _get(orch_raw, "burst_size", 16))),
                voice_async_batch_enabled=_read_bool(os.getenv("ORCH_VOICE_ASYNC_BATCH_ENABLED"), _get(orch_raw, "voice_async_batch_enabled", True)),
                voice_batch_max_size=max(1, _env_int("ORCH_VOICE_BATCH_MAX_SIZE", _get(orch_raw, "voice_batch_max_size", 8))),
                voice_batch_collect_window_ms=max(1, _env_int("ORCH_VOICE_BATCH_COLLECT_WINDOW_MS", _get(orch_raw, "voice_batch_collect_window_ms", 8))),
                voice_batch_result_wait_sec=max(0.05, float(_env_str("ORCH_VOICE_BATCH_RESULT_WAIT_SEC", _get(orch_raw, "voice_batch_result_wait_sec", 1.2)))),
                voice_batch_congested_queue_size=max(1, _env_int("ORCH_VOICE_CONGESTED_QUEUE_SIZE", _get(orch_raw, "voice_batch_congested_queue_size", 12))),
                voice_batch_result_wait_sec_congested=max(0.0, float(_env_str("ORCH_VOICE_BATCH_RESULT_WAIT_SEC_CONGESTED", _get(orch_raw, "voice_batch_result_wait_sec_congested", 0.4)))),
                voice_hit_priority_direct_enabled=_read_bool(os.getenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_ENABLED"), _get(orch_raw, "voice_hit_priority_direct_enabled", True)),
                voice_hit_priority_direct_timeout_sec=max(0.1, float(_env_str("ORCH_VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC", _get(orch_raw, "voice_hit_priority_direct_timeout_sec", 8.0)))),
                circuit_fail_threshold=_env_int("ORCH_CIRCUIT_FAIL_THRESHOLD", _get(orch_raw, "circuit_fail_threshold", 3)),
                circuit_cooldown_sec=float(_env_str("ORCH_CIRCUIT_COOLDOWN_SEC", _get(orch_raw, "circuit_cooldown_sec", 30.0))),
                pending_memory_queue_size=max(1, _env_int("ORCH_MEMORY_PENDING_QUEUE_SIZE", _get(orch_raw, "pending_memory_queue_size", 24))),
            ),
            voice=VoiceTuning(
                connect_timeout_sec=_env_int("VOICE_TTS_CONNECT_TIMEOUT_SEC", _get(voice_raw, "connect_timeout_sec", 5)),
                read_timeout_sec=_env_int("VOICE_TTS_READ_TIMEOUT_SEC", _get(voice_raw, "read_timeout_sec", 30)),
                streaming_mode=_env_int("VOICE_TTS_STREAMING_MODE", _get(voice_raw, "streaming_mode", 3)),
                parallel_infer=_read_bool(os.getenv("VOICE_TTS_PARALLEL_INFER"), _get(voice_raw, "parallel_infer", False)),
                min_chunk_length=max(4, _env_int("VOICE_TTS_MIN_CHUNK_LENGTH", _get(voice_raw, "min_chunk_length", 8))),
                overlap_length=max(0, _env_int("VOICE_TTS_OVERLAP_LENGTH", _get(voice_raw, "overlap_length", 1))),
                text_split_method=_env_str("VOICE_TTS_TEXT_SPLIT_METHOD", _get(voice_raw, "text_split_method", "cut1")),
                buffered_fallback_enabled=_read_bool(os.getenv("TTS_ENABLE_BUFFERED_FALLBACK"), _get(voice_raw, "buffered_fallback_enabled", True)),
                system_tts_fallback_enabled=_read_bool(os.getenv("VOICE_ENABLE_SYSTEM_TTS_FALLBACK"), _get(voice_raw, "system_tts_fallback_enabled", True)),
                cpp_accel_lib=_env_str("VOICE_CPP_ACCEL_LIB", _get(voice_raw, "cpp_accel_lib", ""), allow_empty=True),
                wav_output_dir=_env_str("VOICE_WAV_OUTPUT_DIR", _get(voice_raw, "wav_output_dir", "data/temp")),
                wav_cleanup_enabled=_read_bool(os.getenv("VOICE_WAV_CLEANUP_ENABLED"), _get(voice_raw, "wav_cleanup_enabled", True)),
                wav_cleanup_interval_sec=max(5.0, float(_env_str("VOICE_WAV_CLEANUP_INTERVAL_SEC", _get(voice_raw, "wav_cleanup_interval_sec", 120)))),
                wav_ttl_sec=max(30.0, float(_env_str("VOICE_WAV_TTL_SEC", _get(voice_raw, "wav_ttl_sec", 1800)))),
            ),
            expression=ExpressionTuning(
                auto_reset_sec=float(_env_str("LOCAL_EXPRESSION_AUTO_RESET_SEC", _get(expr_raw, "auto_reset_sec", 2.4))),
                min_timer_gap_ms=max(40, _env_int("LOCAL_EXPRESSION_MIN_TIMER_GAP_MS", _get(expr_raw, "min_timer_gap_ms", 120))),
                timeline_play_motion=_read_bool(os.getenv("LOCAL_EXPRESSION_TIMELINE_PLAY_MOTION"), _get(expr_raw, "timeline_play_motion", False)),
                min_segment_sec=float(_env_str("LOCAL_EXPRESSION_MIN_SEGMENT_SEC", _get(expr_raw, "min_segment_sec", 0.30))),
                min_hold_sec=float(_env_str("LOCAL_EXPRESSION_MIN_HOLD_SEC", _get(expr_raw, "min_hold_sec", 0.55))),
                switch_margin=float(_env_str("LOCAL_EXPRESSION_SWITCH_MARGIN", _get(expr_raw, "switch_margin", 0.10))),
                continuity_bias=float(_env_str("LOCAL_EXPRESSION_CONTINUITY_BIAS", _get(expr_raw, "continuity_bias", 0.12))),
                smooth_window_sec=float(_env_str("LOCAL_EXPRESSION_SMOOTH_WINDOW_SEC", _get(expr_raw, "smooth_window_sec", 0.55))),
                neutral_tail_sec=float(_env_str("LOCAL_EXPRESSION_NEUTRAL_TAIL_SEC", _get(expr_raw, "neutral_tail_sec", 0.26))),
            ),
            gateway=GatewayTuning(
                chat_timeout_sec=float(_env_str("GATEWAY_CHAT_TIMEOUT_SEC", _get(gw_raw, "chat_timeout_sec", 60.0))),
                api_key=(os.getenv("GATEWAY_API_KEY", _get(gw_raw, "api_key", "")) or "").strip(),
            ),
            client=ClientTuning(
                user_id=(os.getenv("LOCAL_GUI_USER_ID", _get(cli_raw, "user_id", "local-gui")) or "local-gui").strip(),
                request_timeout_sec=_env_int("CLIENT_REQUEST_TIMEOUT_SEC", _get(cli_raw, "request_timeout_sec", 30)),
            ),
        )


# ===================== 工厂函数 & 单例 =====================


def load_tuning(path: Optional[str] = None) -> TuningConfig:
    """加载行为调优配置。

    Args:
        path: tuning.yaml 路径（默认为项目根目录的 tuning.yaml）

    Returns:
        填充好的 TuningConfig 实例
    """
    return TuningConfig.from_yaml(path)


# 模块级单例（惰性初始化）
_tuning_instance: Optional[TuningConfig] = None


def get_tuning() -> TuningConfig:
    """获取全局 TuningConfig 单例（首次调用时加载）。"""
    global _tuning_instance
    if _tuning_instance is None:
        _tuning_instance = load_tuning()
    return _tuning_instance
