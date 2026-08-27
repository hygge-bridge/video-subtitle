# -*- coding: utf-8 -*-
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

VIDEO = sys.argv[1]
BASE = os.path.splitext(VIDEO)[0]
EN_SRT = BASE + ".en.srt"
ZH_SRT = BASE + ".zh.srt"
ASS_FILE = BASE + ".zh_en.ass"
OUT = os.path.join(OUT_DIR, os.path.basename(os.path.splitext(VIDEO)[0]) + ".mp4")


def run(cmd):
    return subprocess.run(cmd, cwd=BASE_DIR, capture_output=True)


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
    print("    transcribing (this may take a while)...", flush=True)
    segments, info = model.transcribe(video, language="en", beam_size=5)
    count = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, srt_ts(seg.start), srt_ts(seg.end), seg.text.strip()))
            count = i
            if i % 50 == 0:
                print("    transcribed %d segments (~%.1f min)" % (i, seg.end / 60.0), flush=True)
    os.replace(tmp, en_srt)
    print("    transcription done: %d segments" % count, flush=True)
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
    print("    translating %d segments..." % len(texts), flush=True)
    zh = translate_all(texts)
    with open(tmp, "w", encoding="utf-8") as f:
        for i, (s, e, _) in enumerate(items, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, srt_ts(s), srt_ts(e), zh[i - 1]))
    os.replace(tmp, zh_srt)
    print("    translation done", flush=True)
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


def burn(video, out, ass_text):
    tmp = "_subs_tmp.ass"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(ass_text)
    part = out + ".part.mp4"
    if os.path.exists(part):
        os.remove(part)
    try:
        cmd = ["ffmpeg", "-y", "-i", video, "-vf", "subtitles=_subs_tmp.ass",
               "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", part]
        print("    burning subtitles into mp4 (this takes a while)...", flush=True)
        r = run(cmd)
        if r.returncode != 0:
            return False, r.stderr.decode("utf-8", "ignore")
        os.replace(part, out)
        return True, ""
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    print("input: %s" % VIDEO, flush=True)
    if os.path.exists(OUT):
        print("output already exists: %s" % OUT, flush=True)
        return

    w, h = get_res(VIDEO)
    print("resolution: %dx%d" % (w, h), flush=True)

    print("loading model...", flush=True)
    model = WhisperModel("small.en", device="cuda", compute_type="float16")

    if os.path.exists(EN_SRT):
        print("using existing %s" % EN_SRT, flush=True)
        items = parse_srt(EN_SRT)
    else:
        items = transcribe(model, VIDEO, EN_SRT)

    if os.path.exists(ZH_SRT):
        print("using existing %s" % ZH_SRT, flush=True)
        zh = [t for _, _, t in parse_srt(ZH_SRT)]
    else:
        zh = translate(items, ZH_SRT)

    ass_text = make_ass(w, h, items, zh)
    with open(ASS_FILE, "w", encoding="utf-8") as f:
        f.write(ass_text)
    print("ass saved: %s" % ASS_FILE, flush=True)

    ok, err = burn(VIDEO, OUT, ass_text)
    if not ok:
        print("BURN FAILED: %s" % err[-500:], flush=True)
        return
    print("DONE -> %s" % OUT, flush=True)


if __name__ == "__main__":
    main()