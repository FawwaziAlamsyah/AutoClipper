import subprocess
from pathlib import Path

ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokKinetic,Anton,76,&H00FFFFFF&,&H0000FFFF&,&H00000000&,&H80000000&,1,0,0,0,100,100,1,0,1,8,2,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,TikTokKinetic,,0,0,0,,{\\pos(540,1280)\\fscx106\\fscy106\\t(0,70,\\fscx100\\fscy100)}{\\c&H00E6FF&}GILA{\\c&HFFFFFF&} BANGET
Dialogue: 0,0:00:02.00,0:00:04.00,TikTokKinetic,,0,0,0,,{\\pos(540,1280)\\fscx106\\fscy106\\t(0,70,\\fscx100\\fscy100)}INI {\\c&H00E6FF&}EPIC{\\c&HFFFFFF&} GUYS
"""

scratch_dir = Path("scratch")
scratch_dir.mkdir(exist_ok=True)
ass_file = (scratch_dir / "test_sub.ass").resolve()
ass_file.write_text(ass_content, encoding="utf-8")

# Windows ffmpeg subtitle filter path formatting
# When using subtitles= filter on Windows, colons in drive letters need escaping: C\:/...
ass_str = ass_file.as_posix().replace(":", "\\:")
fontsdir = Path("data/assets/fonts").resolve().as_posix().replace(":", "\\:")

vf = f"subtitles='{ass_str}':fontsdir='{fontsdir}'"
out_img = scratch_dir / "test_sub_frame.png"

cmd = [
    "ffmpeg", "-y", "-ss", "0.5",
    "-i", "data/outputs/clip_3727_11059_8a3ee3dd.mp4",
    "-vf", vf,
    "-vframes", "1",
    str(out_img),
]
res = subprocess.run(cmd, capture_output=True, text=True)
print("Returncode:", res.returncode)
if res.returncode != 0:
    print("Stderr:", res.stderr[-1000:])
else:
    print("Success! Generated:", out_img)
