# 视频中英双语字幕工具

给英文视频自动生成中英双语字幕，并烧录进画面（成片为硬字幕，任意播放器都能显示）。

处理流程：语音识别英文 → 机翻中文 → 生成双语 ASS 字幕 → ffmpeg 烧录。

- 中文：上方，黄色
- 英文：下方，青色

## 环境要求

1. Python 3.13+
2. ffmpeg（需在系统 PATH 中）

   ```powershell
   winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
   ```

   安装后需重开终端使 PATH 生效。

3. Python 依赖

   ```powershell
   pip install faster-whisper deep-translator
   ```

4. （可选，强烈建议）NVIDIA GPU：转写用 CUDA 加速，烧录用 NVENC 硬编码，速度显著快于纯 CPU。

## 推荐用法：process_video.py

最完整的单视频处理脚本，推荐使用。

```powershell
python process_video.py "视频文件.webm"
# 也支持 mp4 等 ffmpeg 能识别的格式
```

功能：

- GPU 转写英文（无 GPU 时把脚本里 `device="cuda"` 改回 `device="cpu"`）
- 并发机翻中文
- 自动按分辨率选字幕字号（1080p / 720p）
- 生成双语 ASS 并烧录成 H.264 mp4
- 断点续跑：`.en.srt` / `.zh.srt` 已存在时会跳过对应步骤，中断后重跑即可继续

输出：

- 成品：`Subtitled/<视频名>.mp4`（脚本所在目录下）
- 中间文件：`<视频名>.en.srt`、`<视频名>.zh.srt`、`<视频名>.zh_en.ass`（在视频旁）

## 只要字幕文件：make_subs.py

只做「识别 + 翻译 + 生成字幕文件」，不烧录（CPU 转写、串行翻译）。

```powershell
python make_subs.py "视频文件.mp4"
```

生成：`.en.srt`、`.zh.srt`、`.zh_en.ass`。

## 批处理：batch_subs.py（早期版本）

遍历脚本所在目录下的 `.mp4`，逐个识别+翻译+烧录，输出到 `Subtitled/`。

```powershell
python batch_subs.py
```

> 该脚本为早期版本，翻译并发的稳健性不如 `process_video.py`，批量场景建议改用 `process_video.py` 逐个或循环调用。

## 字幕样式

- 位置：中文、英文都在画面下方，中文在上、英文在下，尽量不遮挡画面主体
- 颜色：中文黄色、英文青色
- 字体：中文微软雅黑、英文 Arial；字号随分辨率自适应

样式写在各脚本的 `HEADER` / `make_ass` 中，可按需修改。

## 注意事项

- 中文字幕由 Google 翻译机翻生成，专业术语可能不够准确，重要内容建议人工校对 `.zh.srt` 后重新烧录（无需重新识别）。
- 需要联网访问翻译服务；频繁调用可能触发限流。