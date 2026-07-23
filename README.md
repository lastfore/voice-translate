# voice-translate

基于 [Seed-VC](https://github.com/Plachtaa/seed-vc) 的本地语音/歌声转换工作区，包含 Seed-VC 源码（含 Web UI 报错增强）、词曲分离/切片/重组脚本与安装文档。

> 上游参考：Plachta/seed-vc。模型权重不纳入版本库，首次运行时会自动下载到 `seed-vc/checkpoints/`。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `docs/` | 安装与排障文档 |
| `scripts/` | 管线脚本（分离、切片、转换、重组、Web UI） |
| `seed-vc/` | Seed-VC 源码（已纳入版本库，模型权重除外） |
| `separator-env/` | 词曲分离与切片 Python 环境（不纳入版本库） |
| `seed-vc-env/` | Seed-VC 推理 Python 环境（不纳入版本库） |
| `input/` | 原始歌曲输入 |
| `output/` | 各阶段产物（separated / slices / converted / merged） |

## 完整管线

```mermaid
flowchart LR
    A[input/song.flac] --> B[separate-audio.bat]
    B --> C[output/separated/]
    C --> D[slice-vocals / slice-vocals-lrc / process-song]
    D --> E[output/slices/]
    E --> F[convert-slices.bat / Web UI]
    F --> G[output/converted/]
    C --> H[merge-audio.bat]
    G --> H
    H --> I[output/merged/mixed.flac]
```

| 阶段 | 脚本 | 文档 |
| --- | --- | --- |
| 1. 词曲分离 | `scripts/separate-audio.bat` | [词曲分离与声乐切片安装指南](docs/词曲分离与声乐切片安装指南.md) |
| 1+2 一键（LRC） | `scripts/process-song.bat` | 同上 §5.4 |
| 2a. VAD 切片 | `scripts/slice-vocals.bat` | 同上 §5.3 |
| 2b. LRC 切片 | `scripts/slice-vocals-lrc.bat` | 同上 §5.4 |
| 3. 歌声转换 | `scripts/convert-slices.bat` 或 `scripts/start-seed-vc-webui.bat` | [Seed-VC 安装指南](docs/Seed-VC安装指南.md) |
| 4. 人声伴奏重组 | `scripts/merge-audio.bat` | [人声伴奏结合安装指南](docs/人声伴奏结合安装指南.md) |

> 分离与 Seed-VC **不要同时占用 GPU**，按顺序串行执行。

## 快速开始

### Web UI（交互式转换）

1. 按 [Seed-VC 安装指南](docs/Seed-VC安装指南.md) 完成 Python 环境与依赖安装
2. 首次运行会自动下载模型到 `seed-vc/checkpoints/`（约 2.5 GB）
3. 安装 **FFmpeg** 并确保 `ffmpeg` 在 PATH 中可用
4. 启动 Web UI：

```powershell
scripts\start-seed-vc-webui.bat
```

5. 浏览器访问 `http://127.0.0.1:7860/`

### 命令行管线（批量处理）

```powershell
# 有 LRC 歌词：分离 + 切片一步完成
scripts\process-song.bat input\song.flac

# 批量歌声转换
scripts\convert-slices.bat output\slices\song

# 重组混音
scripts\merge-audio.bat `
  --vocals output\converted `
  --instrumental "output\separated\song_(Instrumental)_mel_band_roformer_kim_ft_unwa.flac" `
  --reference input\song.flac `
  --profile full
```

## 脚本清单

| 脚本 | 说明 |
| --- | --- |
| `scripts/separate-audio.bat` | 词曲分离 |
| `scripts/process-song.bat` | 词曲分离 + LRC 切片 |
| `scripts/slice-vocals.bat` | Silero VAD 声学切片 |
| `scripts/slice-vocals-lrc.bat` | LRC 时间戳切片 |
| `scripts/convert-slices.bat` | 批量 Seed-VC 切片转换 |
| `scripts/merge-audio.bat` | 人声与伴奏重组混音 |
| `scripts/start-seed-vc-webui.bat` | 启动 Seed-VC Web UI |
| `scripts/stop-seed-vc-webui.bat` | 关闭 Seed-VC Web UI |
| `scripts/repair-separator-model.bat` | 修复损坏的分离模型权重 |

## 本地定制

- `seed-vc/app_svc.py`：已增强 Web UI 报错提示（如 FFmpeg 缺失、文件不存在等）
- 详见各安装指南
