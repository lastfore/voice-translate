# voice-translate

基于 [Seed-VC](https://github.com/Plachtaa/seed-vc) 的本地语音/歌声转换工作区，包含 Seed-VC 源码（含 Web UI 报错增强）、安装文档与启动脚本。

> 上游参考：Plachta/seed-vc。模型权重不纳入版本库，首次运行时会自动下载到 `seed-vc/checkpoints/`。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `docs/` | 安装与排障文档 |
| `scripts/` | Web UI 启动/停止脚本 |
| `seed-vc/` | Seed-VC 源码（已纳入版本库，模型权重除外） |
| `seed-vc/examples/` | Web UI 示例音频 |
| `seed-vc-env/` | Python 虚拟环境（不纳入版本库） |
| `output/` | 推理输出目录 |

## 快速开始

1. Clone 本仓库后，按 `docs/Seed-VC安装指南.md` 完成 Python 环境与依赖安装
2. 首次运行会自动下载模型到 `seed-vc/checkpoints/`（约 2.5 GB）
3. 安装 **FFmpeg** 并确保 `ffmpeg` 在 PATH 中可用（流式 MP3 输出需要）
4. 启动 Web UI：

```powershell
scripts\start-seed-vc-webui.bat
```

5. 浏览器访问 `http://127.0.0.1:7860/`

## 本地定制

- `seed-vc/app_svc.py`：已增强 Web UI 报错提示（如 FFmpeg 缺失、文件不存在等）
- 详见 `docs/Seed-VC安装指南.md`
