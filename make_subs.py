# -*- coding: utf-8 -*-
"""
为视频自动生成中英双语 ASS 字幕。
流程：faster-whisper 识别英文 -> deep-translator 机翻中文 -> 输出 .ass/.srt
用法：python make_subs.py "视频文件.mp4"
"""
import sys
import os
import re

VIDEO = sys.argv[1]
BASE = os.path.splitext(VIDEO)[0]

from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator, MyMemoryTranslator

print("[1/4] 加载语音识别模型 (small.en)...")
model = WhisperModel("small.en", device="cpu", compute_type="int8")

print("[2/4] 识别英文语音...")
segments, info = model.transcribe(VIDEO, language="en", beam_size=5)
segments = list(segments)
print("    识别到 %d 段字幕" % len(segments))

def to_srt(sec):
    sec = max(0.0, sec)
    ms = int(round(sec * 1000))
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    milli = ms % 1000
    return "%02d:%02d:%02d,%03d" % (h, m, s, milli)

def to_ass(sec):
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h = cs // 360000
    m = (cs % 360000) // 6000
    s = (cs % 6000) // 100
    c = cs % 100
    return "%d:%02d:%02d.%02d" % (h, m, s, c)

def clean(text):
    return text.strip()

gt = GoogleTranslator(source="en", target="zh-CN")

def translate(text):
    t = clean(text)
    if not t:
        return ""
    try:
        return gt.translate(t)
    except Exception:
        try:
            return MyMemoryTranslator(source="en", target="zh-CN").translate(t)
        except Exception:
            return t

# 先批量翻译
print("[3/4] 翻译为中文...")
zh_texts = []
for i, seg in enumerate(segments):
    z = translate(seg.text)
    zh_texts.append(z)
    if (i + 1) % 10 == 0:
        print("    已翻译 %d/%d 段" % (i + 1, len(segments)))

# 写英文/中文 SRT
with open(BASE + ".en.srt", "w", encoding="utf-8") as f:
    for i, seg in enumerate(segments):
        f.write("%d\n%s --> %s\n%s\n\n" % (i + 1, to_srt(seg.start), to_srt(seg.end), clean(seg.text)))

with open(BASE + ".zh.srt", "w", encoding="utf-8") as f:
    for i, seg in enumerate(segments):
        f.write("%d\n%s --> %s\n%s\n\n" % (i + 1, to_srt(seg.start), to_srt(seg.end), zh_texts[i]))

# 写双语 ASS（中文在上-黄色，英文在下-青色）
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

with open(BASE + ".zh_en.ass", "w", encoding="utf-8") as f:
    f.write(HEADER)
    for i, seg in enumerate(segments):
        st = to_ass(seg.start)
        en = to_ass(seg.end)
        cn = zh_texts[i].replace("\n", " ")
        ent = clean(seg.text).replace("\n", " ")
        f.write("Dialogue: 0,%s,%s,CN,,0,0,0,,%s\n" % (st, en, cn))
        f.write("Dialogue: 0,%s,%s,EN,,0,0,0,,%s\n" % (st, en, ent))

print("[4/4] 完成，已生成：")
print("  " + BASE + ".en.srt")
print("  " + BASE + ".zh.srt")
print("  " + BASE + ".zh_en.ass")