# -*- coding: utf-8 -*-
"""
一键字幕工具
用法：python run.py "视频文件"

自动完成：识别英文语音 -> 机翻中文 -> 生成双语字幕 -> 烧录成 mp4
输出：Subtitled/<视频名>.mp4（脚本所在目录下）

支持 mp4 / webm 等 ffmpeg 能识别的格式。
自动检测 NVIDIA GPU：有 GPU 用 CUDA 转写 + NVENC 烧录，无 GPU 则回退 CPU。
"""
import os
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "Subtitled")
os.makedirs(OUT_DIR, exist_ok=True)

from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator, MyMemoryTranslator

VIDEO = os.path.abspath(sys.argv[1])
BASE = os.path.splitext(VIDEO)[0]
EN_SRT = BASE + ".en.srt"
ZH_SRT = BASE + ".zh.srt"
ASS_FILE = BASE + ".zh_en.ass"
OUT = os.path.join(OUT_DIR, os.path.basename(os.path.splitext(VIDEO)[0]) + ".mp4")


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
    segments, info = model.transcribe(video, language="en", beam_size=5)
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
    try:
        return _get_gt().translate(t)
    except Exception:
        try:
            return MyMemoryTranslator(source="en", target="zh-CN").translate(t)
        except Exception:
            return t


def translate_all(texts):
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(translate_one, texts))


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
    tmp = "_subs_tmp.ass"
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


def main():
    if not os.path.exists(VIDEO):
        print("文件不存在：%s" % VIDEO)
        sys.exit(1)
    if os.path.exists(OUT):
        print("输出已存在，跳过：%s" % OUT)
        return

    device, compute_type = pick_device()
    print("输入：%s" % VIDEO)
    print("设备：%s" % ("GPU (CUDA)" if device == "cuda" else "CPU"))

    w, h = get_res(VIDEO)
    print("分辨率：%dx%d" % (w, h))

    print("加载模型...", flush=True)
    model = WhisperModel("small.en", device=device, compute_type=compute_type)

    if os.path.exists(EN_SRT):
        print("使用已有英文转写：%s" % EN_SRT)
        items = parse_srt(EN_SRT)
    else:
        items = transcribe(model, VIDEO, EN_SRT)

    if os.path.exists(ZH_SRT):
        print("使用已有中文翻译：%s" % ZH_SRT)
        zh = [t for _, _, t in parse_srt(ZH_SRT)]
    else:
        zh = translate(items, ZH_SRT)

    ass_text = make_ass(w, h, items, zh)
    with open(ASS_FILE, "w", encoding="utf-8") as f:
        f.write(ass_text)

    ok, err = burn(VIDEO, OUT, ass_text, device)
    if not ok:
        print("烧录失败：%s" % err[-500:])
        sys.exit(1)
    print("完成 -> %s" % OUT)


if __name__ == "__main__":
    main()