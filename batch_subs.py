# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "Subtitled")
os.makedirs(OUT_DIR, exist_ok=True)

from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator, MyMemoryTranslator

DONE_SKIP = {"001 Introduction.mp4"}

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CN,Microsoft YaHei,36,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,30,30,80,1
Style: EN,Arial,30,&H00FFFF00,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,36,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def to_ass(sec):
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h = cs // 360000
    m = (cs % 360000) // 6000
    s = (cs % 6000) // 100
    c = cs % 100
    return "%d:%02d:%02d.%02d" % (h, m, s, c)


def clean(t):
    return t.strip()


gt = GoogleTranslator(source="en", target="zh-CN")


def translate(t):
    t = clean(t)
    if not t:
        return ""
    try:
        return gt.translate(t)
    except Exception:
        try:
            return MyMemoryTranslator(source="en", target="zh-CN").translate(t)
        except Exception:
            return t


def translate_all(texts):
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(translate, texts))


def write_ass(base, segments, zh):
    ass = base + ".zh_en.ass"
    with open(ass, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for seg, z in zip(segments, zh):
            st = to_ass(seg.start)
            en = to_ass(seg.end)
            cn = z.replace("\n", " ")
            ent = clean(seg.text).replace("\n", " ")
            f.write("Dialogue: 0,%s,%s,CN,,0,0,0,,%s\n" % (st, en, cn))
            f.write("Dialogue: 0,%s,%s,EN,,0,0,0,,%s\n" % (st, en, ent))
    return ass


def burn(video, ass, out):
    vf = "subtitles=filename='%s'" % ass
    cmd = ["ffmpeg", "-y", "-i", video, "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "copy", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True)
    if r.returncode != 0:
        return r.returncode, r.stderr.decode("utf-8", "ignore")
    return r.returncode, ""


def main():
    print("loading model...")
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    videos = sorted([f for f in os.listdir(BASE_DIR) if f.lower().endswith(".mp4")])
    total = len(videos)
    done = 0
    failed = []
    for idx, v in enumerate(videos, 1):
        if v in DONE_SKIP:
            print("[%d/%d] skip (already subtitled) %s" % (idx, total, v), flush=True)
            continue
        out = os.path.join(OUT_DIR, v)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            print("[%d/%d] skip (exists) %s" % (idx, total, v), flush=True)
            continue
        base = os.path.splitext(v)[0]
        print("[%d/%d] transcribe+translate %s" % (idx, total, v), flush=True)
        try:
            segs, info = model.transcribe(v, language="en", beam_size=5)
            segs = list(segs)
            print("    transcribed %d segments, translating..." % len(segs), flush=True)
            zh = translate_all([s.text for s in segs])
            ass = write_ass(base, segs, zh)
            print("    translated, burning...", flush=True)
            rc, err = burn(v, ass, out)
            if rc != 0:
                print("    burn FAILED: %s" % err[-300:], flush=True)
                failed.append(v)
            else:
                done += 1
                print("    OK -> Subtitled\\%s" % v, flush=True)
        except Exception as e:
            print("    ERROR: %s" % e, flush=True)
            failed.append(v)
    print("\nALL DONE. succeeded=%d failed=%d" % (done, len(failed)), flush=True)
    if failed:
        print("failed list: %s" % failed, flush=True)


if __name__ == "__main__":
    main()