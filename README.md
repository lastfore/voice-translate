# voice-translate

基于 [Seed-VC](https://github.com/Plachtaa/seed-vc) 的本地语音/歌声转换工作区，包含安装文档、启动脚本，以及对 Web UI 的报错增强补丁。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `docs/` | 安装与排障文档 |
| `scripts/` | Web UI 启动/停止脚本 |
| `patches/` | 对上游 `seed-vc` 的本地补丁 |
| `seed-vc/` | Seed-VC 源码（需单独 clone，见安装指南） |
| `seed-vc-env/` | Python 虚拟环境（不纳入版本库） |
| `output/` | 推理输出目录 |

## 快速开始

1. 按 `docs/Seed-VC安装指南.md` 完成环境与模型安装
2. 应用本地补丁（可选，用于更清晰的 Web UI 报错）：

```powershell
Copy-Item -Force patches\app_svc.py seed-vc\app_svc.py
```

3. 启动 Web UI：

```powershell
scripts\start-seed-vc-webui.bat
```

4. 浏览器访问 `http://127.0.0.1:7860/`

## 依赖说明

- 流式 MP3 输出需要系统已安装 **FFmpeg** 且 `ffmpeg` 在 PATH 中可用
- 详见 `docs/Seed-VC安装指南.md`
