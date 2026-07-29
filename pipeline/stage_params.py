"""Stage parameter schema — single source of truth for defaults and UI metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pipeline import paths
from pipeline.models import StageName
from pipeline.stages.separate import DEFAULT_MODEL

ParamType = Literal["int", "float", "bool", "choice", "str"]
ChoicesFn = Callable[[], list[str]]


@dataclass(frozen=True)
class StageParam:
    key: str
    label: str
    description: str
    param_type: ParamType
    default: Any
    choices: tuple[str, ...] | None = None
    choices_fn: ChoicesFn | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    wizard: bool = False
    # VAD-only params; ignored when slice mode is LRC
    vad_only: bool = False
    # LRC-only params; ignored when slice mode is VAD
    lrc_only: bool = False
    # Convert mode filters
    slice_batch_only: bool = False
    full_track_only: bool = False


def list_separator_models() -> list[str]:
    model_dir = paths.get_separator_env() / "models" / "audio-separator"
    if not model_dir.is_dir():
        return [DEFAULT_MODEL]
    exts = {".ckpt", ".yaml", ".yml", ".onnx", ".pth"}
    names = sorted(p.name for p in model_dir.iterdir() if p.is_file() and p.suffix.lower() in exts)
    return names or [DEFAULT_MODEL]


# Known MelBand / RoFormer models — used for Web UI comparison hints.
SEPARATOR_MODEL_PROFILES: dict[str, dict[str, str]] = {
    "mel_band_roformer_kim_ft_unwa.ckpt": {
        "quality": "高 (~12.4 dB)",
        "speed": "快",
        "vram": "低 (~4 GB)",
        "recommend": "默认推荐，显存友好、bleed 低",
    },
    "vocals_mel_band_roformer.ckpt": {
        "quality": "高 (~12.6 dB)",
        "speed": "中",
        "vram": "中 (~6 GB)",
        "recommend": "Kimberley Jensen 微调版，音质略优",
    },
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
        "quality": "最高 (~13.0 dB)",
        "speed": "慢",
        "vram": "高 (~8 GB+)",
        "recommend": "追求最佳分离质量时选用",
    },
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt": {
        "quality": "中（净化专用）",
        "speed": "中",
        "vram": "中 (~6 GB)",
        "recommend": "仅用于合并时净化伴奏，不作主分离模型",
    },
}


def separator_model_comparison_markdown() -> str:
    """Markdown table comparing separator models for the Web UI."""
    lines = [
        "### 分离模型对比",
        "",
        "| 模型 | 分离质量 | 速度 | 显存 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, profile in SEPARATOR_MODEL_PROFILES.items():
        lines.append(
            f"| `{name}` | {profile['quality']} | {profile['speed']} | "
            f"{profile['vram']} | {profile['recommend']} |"
        )
    installed = set(list_separator_models())
    for name in sorted(installed):
        if name in SEPARATOR_MODEL_PROFILES:
            continue
        lines.append(f"| `{name}` | — | — | — | 已安装，详见 audio-separator 文档 |")
    lines.extend(
        [
            "",
            "**推荐：** 日常使用 `mel_band_roformer_kim_ft_unwa.ckpt`（质量与速度均衡）；"
            "显存充足且追求极致音质选 `model_bs_roformer_ep_317_sdr_12.9755.ckpt`；"
            "仅需快速试听可尝试 MDX 系列（质量较低但速度最快）。",
        ]
    )
    return "\n".join(lines)


STAGE_PARAMS: dict[str, list[StageParam]] = {
    StageName.SEPARATE.value: [
        StageParam(
            key="model",
            label="分离模型",
            description=(
                "MelBand-RoFormer 模型文件。"
                "默认 mel_band_roformer_kim_ft_unwa.ckpt 质量与速度均衡；"
                "model_bs_roformer_ep_317_sdr_12.9755.ckpt 质量最高但较慢；"
                "MDX 系列速度最快但质量较低。详见下方对比表。"
            ),
            param_type="choice",
            default=DEFAULT_MODEL,
            choices_fn=list_separator_models,
            wizard=True,
        ),
    ],
    StageName.SLICE.value: [
        StageParam(
            key="vad_threshold",
            label="VAD 灵敏度",
            description="语音检测阈值（0~1）。越低越容易切出片段，可能含更多噪声；越高则更保守。",
            param_type="float",
            default=0.45,
            minimum=0.1,
            maximum=0.95,
            step=0.05,
            wizard=True,
            vad_only=True,
        ),
        StageParam(
            key="min_speech_ms",
            label="最短语音 (ms)",
            description="短于此长度的片段会被丢弃，用于过滤呼吸声、碎音。",
            param_type="int",
            default=250,
            minimum=50,
            maximum=5000,
            step=50,
            vad_only=True,
        ),
        StageParam(
            key="min_silence_ms",
            label="最短静音 (ms)",
            description="相邻语音之间至少间隔多长静音才切分，避免一句被切成多段。",
            param_type="int",
            default=500,
            minimum=100,
            maximum=5000,
            step=50,
            vad_only=True,
        ),
        StageParam(
            key="speech_pad_ms",
            label="切片留白 (ms)",
            description="每段语音首尾额外保留的缓冲，减少切边造成的爆音或咬字缺失。",
            param_type="int",
            default=80,
            minimum=0,
            maximum=500,
            step=10,
            vad_only=True,
        ),
        StageParam(
            key="boundary_mode",
            label="边界模式",
            description=(
                "LRC 相邻句切点策略。"
                "起音对齐会在下一行 LRC 戳前检测真实起唱并前移切点；"
                "LRC 严格模式与旧版行为一致。"
            ),
            param_type="choice",
            default="onset_aligned",
            choices=("onset_aligned", "lrc_strict"),
            wizard=True,
            lrc_only=True,
        ),
        StageParam(
            key="search_margin_ms",
            label="起音搜索回溯 (ms)",
            description="从下一行 LRC 时间戳向前回溯的最大搜索距离。",
            param_type="int",
            default=400,
            minimum=50,
            maximum=2000,
            step=50,
            lrc_only=True,
        ),
        StageParam(
            key="onset_min_lead_silence_ms",
            label="起音前最短静音 (ms)",
            description="起音点前要求的最短低能量区间，用于区分换气与本句尾音。",
            param_type="int",
            default=80,
            minimum=20,
            maximum=500,
            step=10,
            lrc_only=True,
        ),
        StageParam(
            key="min_slice_ms",
            label="最短切片 (ms)",
            description="对齐后任一句短于此值时，该边界回退到 LRC 时间戳。",
            param_type="int",
            default=500,
            minimum=100,
            maximum=5000,
            step=50,
            lrc_only=True,
        ),
        StageParam(
            key="onset_energy_threshold_db",
            label="起音能量阈值 (dB)",
            description=(
                "相对搜索窗口峰值 RMS 的起音检测阈值（dB）。"
                "数值越大（如 -35）越敏感；越小（如 -45）越保守。"
            ),
            param_type="float",
            default=-40.0,
            minimum=-60.0,
            maximum=-20.0,
            step=1.0,
            lrc_only=True,
        ),
    ],
    StageName.CONVERT.value: [
        StageParam(
            key="diffusion_steps",
            label="扩散步数",
            description="Seed-VC 推理步数。步数越多音质通常越稳，但耗时更长；40 为常用平衡点。",
            param_type="int",
            default=40,
            minimum=4,
            maximum=100,
            step=1,
            wizard=True,
        ),
        StageParam(
            key="length_adjust",
            label="时长缩放",
            description="输出相对输入的时长比例。1.0 保持原长；略大于 1 可拉长尾音。",
            param_type="float",
            default=1.0,
            minimum=0.5,
            maximum=2.0,
            step=0.05,
        ),
        StageParam(
            key="inference_cfg_rate",
            label="CFG 强度",
            description="分类器引导强度。越高越贴近参考音色，过高可能出现失真或机械感。",
            param_type="float",
            default=0.7,
            minimum=0.0,
            maximum=1.0,
            step=0.05,
            wizard=True,
        ),
        StageParam(
            key="auto_f0_adjust",
            label="自动 F0 对齐",
            description="根据参考音频自动调整音高轮廓，使转换后人声更自然贴合旋律。",
            param_type="bool",
            default=True,
            wizard=True,
        ),
        StageParam(
            key="semi_tone_shift",
            label="半音移调",
            description="在转换基础上整体升降调（半音）。男转女可试 +4~+8，女转男可试 -4~-8。",
            param_type="int",
            default=0,
            minimum=-12,
            maximum=12,
            step=1,
            wizard=True,
        ),
        StageParam(
            key="fp16",
            label="FP16 推理",
            description="半精度加速推理，显存占用更低。若遇数值异常可关闭改用 FP32。",
            param_type="bool",
            default=True,
        ),
        StageParam(
            key="skip_existing",
            label="跳过已有切片",
            description="切片批量模式下，已存在输出文件的切片不再重复转换，便于断点续跑。",
            param_type="bool",
            default=True,
            slice_batch_only=True,
        ),
        StageParam(
            key="limit",
            label="试跑片数",
            description="切片批量模式下仅转换前 N 片（0 表示全部），用于快速试听参数效果。",
            param_type="int",
            default=0,
            minimum=0,
            maximum=9999,
            step=1,
            slice_batch_only=True,
        ),
    ],
    StageName.MERGE.value: [
        StageParam(
            key="vocals_gain_db",
            label="人声增益 (dB)",
            description="合并前对人声轨施加的音量调整。正值让人声更突出，负值则压低。",
            param_type="float",
            default=0.0,
            minimum=-12.0,
            maximum=12.0,
            step=0.5,
            wizard=True,
        ),
        StageParam(
            key="instrumental_gain_db",
            label="伴奏增益 (dB)",
            description="合并前对伴奏轨施加的音量调整，用于平衡人声与伴奏比例。",
            param_type="float",
            default=0.0,
            minimum=-12.0,
            maximum=12.0,
            step=0.5,
            wizard=True,
        ),
        StageParam(
            key="clean_instrumental",
            label="Karaoke 净化伴奏",
            description="用模型进一步削弱伴奏中残留人声（需 full profile）。适合分离不干净时尝试。",
            param_type="bool",
            default=False,
        ),
        StageParam(
            key="skip_mastering",
            label="跳过母带处理",
            description="不执行 Matchering 母带匹配，输出未经响度/频谱优化的混合曲。",
            param_type="bool",
            default=False,
        ),
    ],
}


def params_for_stage(stage: str, *, wizard_only: bool = False) -> list[StageParam]:
    items = STAGE_PARAMS.get(stage, [])
    if wizard_only:
        return [p for p in items if p.wizard]
    return list(items)


def partition_bool_params(param_list: list[StageParam]) -> tuple[list[StageParam], list[StageParam]]:
    """Split bool params out — Gradio accordions may drop checkbox values when collapsed."""
    bool_params = [p for p in param_list if p.param_type == "bool"]
    other_params = [p for p in param_list if p.param_type != "bool"]
    return bool_params, other_params


def default_stage_params(stage: str, *, wizard_only: bool = False) -> dict[str, Any]:
    return {p.key: resolve_default(p) for p in params_for_stage(stage, wizard_only=wizard_only)}


def resolve_default(param: StageParam) -> Any:
    if param.choices_fn is not None:
        choices = param.choices_fn()
        if param.default in choices:
            return param.default
        return choices[0] if choices else param.default
    return param.default


def merge_stage_params(stage: str, saved: dict[str, Any] | None, *, wizard_only: bool = False) -> dict[str, Any]:
    merged = default_stage_params(stage, wizard_only=wizard_only)
    if not saved:
        return merged
    schema = {p.key: p for p in params_for_stage(stage, wizard_only=wizard_only)}
    for key, value in saved.items():
        if key not in schema or value is None:
            continue
        merged[key] = coerce_param_value(schema[key], value)
    return merged


def coerce_param_value(param: StageParam, value: Any) -> Any:
    if param.param_type == "bool":
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if param.param_type == "int":
        return int(value)
    if param.param_type == "float":
        return float(value)
    if param.param_type == "choice":
        choices = list(param.choices or ())
        if param.choices_fn is not None:
            choices = param.choices_fn()
        if value in choices:
            return value
        return resolve_default(param)
    return str(value)


def collect_params(
    stage: str,
    values: dict[str, Any],
    *,
    slice_mode: str | None = None,
    convert_mode: str | None = None,
) -> dict[str, Any]:
    """Filter params for stage execution (e.g. drop VAD keys in LRC mode)."""
    schema = {p.key: p for p in params_for_stage(stage)}
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in schema:
            continue
        param = schema[key]
        if param.vad_only and slice_mode and slice_mode != "vad":
            continue
        if param.lrc_only and slice_mode and slice_mode != "lrc":
            continue
        if param.slice_batch_only and convert_mode and convert_mode != "slice_batch":
            continue
        if param.full_track_only and convert_mode and convert_mode != "full_track":
            continue
        out[key] = coerce_param_value(param, value)
    return out


def wizard_param_keys() -> list[str]:
    keys: list[str] = []
    for stage in StageName:
        for param in params_for_stage(stage.value, wizard_only=True):
            keys.append(param.key)
    return keys


def merge_wizard_params(saved_by_stage: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for stage in StageName:
        stage_saved = (saved_by_stage or {}).get(stage.value, {})
        merged.update(merge_stage_params(stage.value, stage_saved, wizard_only=True))
    return merged
