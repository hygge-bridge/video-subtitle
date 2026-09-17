# 视频中英双语字幕工具

给英文视频自动生成中英双语字幕，并烧录进画面（成片为硬字幕，任意播放器都能显示）。

## 目录结构

```
.
├── input/           放原始视频
├── output/          加字幕后成品 mp4
├── intermediate/    中间文件（.srt / .ass）
├── run.py           一键脚本
└── README.md
```

## 使用说明

### 一键生成（推荐）

1. 把原始视频放进 `input/` 目录。
2. 运行：

   ```powershell
   python run.py
   ```

   会自动处理 `input/` 下所有视频，成品输出到 `output/`，中间文件放在 `intermediate/`。

也可以只处理某一个视频：

```powershell
python run.py "视频文件"
```

### 只识别生成英文字幕（跳过翻译和烧录）

```powershell
python run.py --subs-only                # input/ 下所有视频
python run.py --subs-only "视频文件"      # 指定单个视频
```

只做语音识别，生成英文 `.srt` 到 `intermediate/`，不翻译、不烧录，适合只想拿到字幕再自行处理的情况。

### 快跑模式（榨干系统资源）

```powershell
python run.py --fast                       # input/ 下多个视频并发处理
python run.py --fast --subs-only           # 快跑 + 只识别不翻译不烧录
```

适合处理时不需要留给其它程序占用资源的场景（不打游戏、只是切换微信/浏览器）。

- 同时处理多个视频（默认并发 2 个，按本机 8GB 显存/32 核 CPU 配置；可在 `run.py` 的 `FAST_WORKERS` 调整）
- 单个视频识别时关闭串行依赖（`condition_on_previous_text=False`），让语音片段独立并行，不再互相等待

功能：

- 自动检测 NVIDIA GPU：有则 CUDA 转写 + NVENC 烧录，无则回退 CPU
- 自动按分辨率选字幕字号（1080p / 720p）
- 断点续跑：`intermediate/` 下对应模型标识的 `.en.srt` / `.zh.srt` 已存在时会跳过对应步骤
- 语音识别使用 faster-whisper `large-v3` 模型（最准），首次运行会自动下载模型
- `--subs-only` 模式只执行识别，不翻译不烧录

### 只要字幕文件（不烧录）

```powershell
python make_subs.py "视频文件.mp4"
```

只做「识别 + 翻译 + 生成字幕文件」：`.en.srt`、`.zh.srt`、`.zh_en.ass`。

### 批处理（早期版本）

```powershell
python batch_subs.py
```

遍历脚本所在目录下的 `.mp4` 逐个处理。该脚本为早期版本，稳健性不如 `run.py`，批量场景建议用 `run.py` 自动处理 `input/` 目录。

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

## 字幕样式

- 位置：中文、英文都在画面下方，中文在上、英文在下，尽量不遮挡画面主体
- 颜色：中文黄色、英文青色
- 字体：中文微软雅黑、英文 Arial；字号随分辨率自适应

样式写在各脚本的 `HEADER` / `make_ass` 中，可按需修改。

## 注意事项

- 中文字幕由 Google 翻译机翻生成，专业术语可能不够准确，重要内容建议人工校对 `.zh.srt` 后重新烧录（无需重新识别）。
- 需要联网访问翻译服务；频繁调用可能触发限流。