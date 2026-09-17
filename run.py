# -*- coding: utf-8 -*-
"""
一键字幕工具
用法：
  python run.py                 # 自动处理 input/ 目录下所有视频
  python run.py "视频文件"        # 处理指定单个视频

目录结构（脚本所在目录下）：
  input/           放原始视频
  output/          加字幕后成品 mp4
  intermediate/    中间文件（.srt / .ass）

自动检测 NVIDIA GPU：有则 CUDA 转写 + NVENC 烧录，无则回退 CPU。
"""
import os
import sys
import subprocess
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

IN_DIR = os.path.join(BASE_DIR, "input")
OUT_DIR = os.path.join(BASE_DIR, "output")
INTER_DIR = os.path.join(BASE_DIR, "intermediate")
for d in (IN_DIR, OUT_DIR, INTER_DIR):
    os.makedirs(d, exist_ok=True)

from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator, MyMemoryTranslator

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".ts", ".m4v")

# 语音识别模型：large-v3 是 faster-whisper 目前最准的模型（多语言，本脚本固定英文识别）
MODEL_NAME = "large-v3"

# 只识别生成英文字幕，跳过翻译和烧录：python run.py --subs-only [视频]
SUBS_ONLY = "--subs-only" in sys.argv[1:]

# 快跑模式：尽量榨干资源。输入多个视频时并发识别/处理，单项转写取消串行依赖。
# python run.py --fast
FAST = "--fast" in sys.argv[1:]
# 并发数：本机 RTX 5060 8GB 显存 + 32 核 CPU。8GB 显存是上限，large-v3
# 权重约 3GB，每路并发额外占激活内存，取 2 最稳（能并行又不爆显存）。
FAST_WORKERS = 2


def run(cmd):
    return subprocess.run(cmd, cwd=BASE_DIR, capture_output=True)


def pick_device():
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def get_res(video):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video])
    w, h = r.stdout.decode().strip().split(",")
    return int(w), int(h)


def srt_ts(sec):
    sec = max(0.0, sec)
    ms = int(round(sec * 1000))
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    milli = ms % 1000
    return "%02d:%02d:%02d,%03d" % (h, m, s, milli)


def srt_to_sec(ts):
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def ass_ts(sec):
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h = cs // 360000
    m = (cs % 360000) // 6000
    s = (cs % 6000) // 100
    c = cs % 100
    return "%d:%02d:%02d.%02d" % (h, m, s, c)


def parse_srt(path):
    items = []
    with open(path, encoding="utf-8") as f:
        blocks = f.read().strip().split("\n\n")
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 3:
            continue
        times = lines[1].split(" --> ")
        start = srt_to_sec(times[0])
        end = srt_to_sec(times[1])
        text = "\n".join(lines[2:])
        items.append((start, end, text))
    return items


def transcribe(model, video, en_srt):
    tmp = en_srt + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    print("  [1/3] 识别英文语音（耗时较长）...", flush=True)
    segments, info = model.transcribe(
        video,
        language="en",
        beam_size=5,
        vad_filter=True,          # 滤除静音/音乐段，减少错误转写与幻觉
        condition_on_previous_text=not FAST,   # --fast 时关闭，片段可独立并行、不互相等待
    )
    count = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, srt_ts(seg.start), srt_ts(seg.end), seg.text.strip()))
            count = i
            if i % 100 == 0:
                print("        已识别 %d 段（~%.0f 分钟）" % (i, seg.end / 60.0), flush=True)
    os.replace(tmp, en_srt)
    print("  识别完成，共 %d 段" % count, flush=True)
    return parse_srt(en_srt)


_tl = threading.local()


def _get_gt():
    gt = getattr(_tl, "gt", None)
    if gt is None:
        gt = GoogleTranslator(source="en", target="zh-CN")
        _tl.gt = gt
    return gt


def translate_one(t):
    t = t.strip()
    if not t:
        return ""
    last = t
    for _ in range(3):
        try:
            r = _get_gt().translate(t)
            if r and r.strip():
                return r
            last = r
        except Exception:
            time.sleep(1.0)
    try:
        r = MyMemoryTranslator(source="en", target="zh-CN").translate(t)
        if r and r.strip():
            return r
        last = r
    except Exception:
        pass
    return last


def translate_all(texts):
    # 串行翻译，避免并发触发限流；每句多次重试后仍失败才回退原文
    out = []
    for i, t in enumerate(texts):
        out.append(translate_one(t))
        if i % 20 == 0:
            print("        已翻译 %d / %d 段" % (i, len(texts)), flush=True)
    return out


def translate(items, zh_srt):
    tmp = zh_srt + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    texts = [t for _, _, t in items]
    print("  [2/3] 机翻为中文（%d 段）..." % len(texts), flush=True)
    zh = translate_all(texts)
    with open(tmp, "w", encoding="utf-8") as f:
        for i, (s, e, _) in enumerate(items, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, srt_ts(s), srt_ts(e), zh[i - 1]))
    os.replace(tmp, zh_srt)
    print("  翻译完成", flush=True)
    return zh


def make_ass(w, h, items, zh):
    if h >= 900:
        cn_fs, en_fs = 46, 38
        cn_mv, en_mv = 112, 54
    else:
        cn_fs, en_fs = 36, 30
        cn_mv, en_mv = 80, 36
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CN,Microsoft YaHei,%d,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,30,30,%d,1
Style: EN,Arial,%d,&H00FFFF00,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,%d,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % (w, h, cn_fs, cn_mv, en_fs, en_mv)
    lines = [head]
    for (s, e, en_text), z in zip(items, zh):
        st = ass_ts(s)
        et = ass_ts(e)
        cn = z.replace("\n", " ")
        en = en_text.replace("\n", " ")
        lines.append("Dialogue: 0,%s,%s,CN,,0,0,0,,%s\n" % (st, et, cn))
        lines.append("Dialogue: 0,%s,%s,EN,,0,0,0,,%s\n" % (st, et, en))
    return "".join(lines)


def burn(video, out, ass_text, device):
    tmp = os.path.join(BASE_DIR, "_subs_tmp.ass")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(ass_text)
    part = out + ".part.mp4"
    if os.path.exists(part):
        os.remove(part)
    common = ["-vf", "subtitles=_subs_tmp.ass", "-c:a", "aac", "-b:a", "128k",
              "-movflags", "+faststart"]
    try:
        print("  [3/3] 烧录字幕...", flush=True)
        if device == "cuda":
            cmd = ["ffmpeg", "-y", "-i", video] + common + \
                  ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0", part]
            r = run(cmd)
            if r.returncode == 0:
                os.replace(part, out)
                return True, ""
            if os.path.exists(part):
                os.remove(part)
            print("    NVENC 不可用，回退到 CPU 编码", flush=True)
        cmd = ["ffmpeg", "-y", "-i", video] + common + \
              ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", part]
        r = run(cmd)
        if r.returncode != 0:
            return False, r.stderr.decode("utf-8", "ignore")
        os.replace(part, out)
        return True, ""
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def process_one(video, model, device):
    video = os.path.abspath(video)
    if not os.path.exists(video):
        print("文件不存在：%s" % video)
        return False

    base_name = os.path.splitext(os.path.basename(video))[0]
    tag = MODEL_NAME.replace("-", "_")
    en_srt = os.path.join(INTER_DIR, base_name + ".en.%s.srt" % tag)
    zh_srt = os.path.join(INTER_DIR, base_name + ".zh.%s.srt" % tag)
    ass_file = os.path.join(INTER_DIR, base_name + ".zh_en.%s.ass" % tag)
    out = os.path.join(OUT_DIR, base_name + ".%s.mp4" % tag)

    if os.path.exists(out):
        print("成品已存在，跳过：%s" % out)
        return True

    print("\n== 处理：%s ==" % video)
    print("设备：%s" % ("GPU (CUDA)" if device == "cuda" else "CPU"))
    w, h = get_res(video)
    print("分辨率：%dx%d" % (w, h))

    if os.path.exists(en_srt):
        print("使用已有英文转写：%s" % en_srt)
        items = parse_srt(en_srt)
    else:
        items = transcribe(model, video, en_srt)

    if SUBS_ONLY:
        print("已生成英文字幕（识别），跳过翻译和烧录：%s" % en_srt)
        return True

    if os.path.exists(zh_srt):
        print("使用已有中文翻译：%s" % zh_srt)
        zh = [t for _, _, t in parse_srt(zh_srt)]
    else:
        zh = translate(items, zh_srt)

    ass_text = make_ass(w, h, items, zh)
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_text)

    ok, err = burn(video, out, ass_text, device)
    if not ok:
        print("烧录失败：%s" % err[-500:])
        return False
    print("完成 -> %s" % out)
    return True


def main():
    device, compute_type = pick_device()
    # large-v3 精度优先：GPU 用 float16，显存不足时回退 int8_float16（仍为 GPU 推理）
    try:
        model = WhisperModel(MODEL_NAME, device=device, compute_type=compute_type)
    except Exception as e:
        if device == "cuda":
            print("float16 加载失败，回退 int8_float16：%s" % e, flush=True)
            model = WhisperModel(MODEL_NAME, device="cuda", compute_type="int8_float16")
        else:
            raise
    print("识别模型：%s（%s/%s）" % (MODEL_NAME, device, compute_type), flush=True)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        process_one(args[0], model, device)
        return

    videos = sorted([f for f in os.listdir(IN_DIR)
                     if os.path.splitext(f)[1].lower() in VIDEO_EXTS])
    if not videos:
        print("input/ 目录下没有视频。请把视频放入 input/，或运行：python run.py \"视频路径\"")
        return

    from concurrent.futures import ThreadPoolExecutor

    print("发现 %d 个视频待处理" % len(videos))
    ok = 0
    if FAST and len(videos) > 1:
        workers = min(FAST_WORKERS, len(videos))
        print("--fast 模式：并发处理（%d 个同时进行），以榨干系统资源" % workers)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(
                lambda v: process_one(os.path.join(IN_DIR, v), model, device), videos))
        ok = sum(1 for r in results if r)
    else:
        for v in videos:
            if process_one(os.path.join(IN_DIR, v), model, device):
                ok += 1
    print("\n全部结束：成功 %d / 共 %d" % (ok, len(videos)))


if __name__ == "__main__":
    main()