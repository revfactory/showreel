#!/usr/bin/env python3
"""마감: 무음 렌더 영상 + 믹스 → 납품 파일 세트(마스터·공유용·포스터·자막) + 규격 검증.

사용법
  finish.py --video out/video.mp4 --audio audio/mix.wav --name "홍길동_쇼릴_60s" [--outdir out]
            [--poster 57.5] [--timeline timeline.json] [--no-web]

만드는 것 (outdir 아래)
  <name>.mp4          마스터: 영상은 그대로 복사(재인코딩 없음), AAC 320k 48kHz, faststart, BT.709 태그
  <name>_공유용.mp4    메신저·SNS용: x264 CRF 23, 최대 8Mbps, AAC 192k (보통 마스터의 1/3~1/5 크기)
  <name>_포스터.jpg    --poster 초의 프레임(기본: 끝에서 1.5초 전 = 보통 엔드카드)
  <name>.srt          --timeline 이 있고 나레이션이 있으면 자막 파일(번인 자막과 같은 데이터)
마지막에 ffprobe·ebur128 로 규격을 검증해 표로 보여 준다(yuv420p·tv 범위·프레임 수·LUFS·true peak).
오디오만 고쳤다면 영상을 다시 렌더하지 말고 이 스크립트만 다시 돌리면 된다.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"실패: {' '.join(cmd[:6])} …\n{r.stderr[-800:]}")
    return r


def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_type,codec_name,width,height,pix_fmt,color_range,color_space,color_primaries,r_frame_rate,nb_read_frames,sample_rate,channels,bit_rate"
                        ":format=duration,size", "-of", "json", str(path)]).stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    au = next((s for s in d["streams"] if s["codec_type"] == "audio"), {})
    return v, au, d["format"]


def loud(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    s = r[r.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", s).group(1)) if re.search(k + r":\s+(-?[\d.]+)", s) else None
    return g("I"), g("LRA"), g("Peak")


def srt_time(t):
    t = max(0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio")
    ap.add_argument("--name", required=True)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--poster", type=float)
    ap.add_argument("--timeline")
    ap.add_argument("--no-web", action="store_true")
    a = ap.parse_args()
    od = Path(a.outdir)
    od.mkdir(parents=True, exist_ok=True)
    v, _, fmt = probe(a.video)
    vdur = float(fmt["duration"])
    master = od / f"{a.name}.mp4"
    # 색 정보(VUI)를 BT.709 로 확정 — 일부 플레이어가 태그 없는 영상을 다르게 해석한다
    bsf = ["-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.video]
    if a.audio:
        cmd += ["-i", a.audio, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
    cmd += ["-c:v", "copy", *bsf, "-t", f"{vdur:.3f}", "-movflags", "+faststart", str(master)]
    run(cmd)
    outs = [master]
    if not a.no_web:
        web = od / f"{a.name}_공유용.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(master)]
        if a.audio:   # 마스터의 AAC 를 다시 인코딩하면 피크가 올라 보정이 과하게 걸린다(-14 → -17.5 LUFS 사례) → 원본 믹스에서 한 번만 인코딩
            cmd += ["-i", a.audio, "-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "23",
               "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
               "-color_trc", "bt709", "-color_range", "tv"]
        if a.audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{vdur:.3f}", "-movflags", "+faststart", str(web)]
        run(cmd)
        if a.audio:   # AAC 인코딩이 트루 피크를 올릴 수 있다 → 넘으면 원본 믹스에서 음량만 낮춰 다시(영상은 복사). 다시 재서 통과할 때까지 최대 3번
            gain = 0.0    # 이미 AAC 로 만든 공유용을 다시 AAC 로 인코딩하면 피크가 또 올라 보정이 겹쳐 쌓인다(-14 → -17.5 LUFS) → 늘 원본에서, 이득만 누적
            for _ in range(3):
                _, _, tp = loud(web)
                if tp is None or tp <= -1.0:
                    break
                gain += -1.6 - tp
                tmp = web.with_name(web.stem + ".tmp.mp4")
                run(["ffmpeg", "-v", "error", "-y", "-i", str(web), "-i", a.audio, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                     "-af", f"volume={gain:.2f}dB", "-c:a", "aac", "-b:a", "192k", "-t", f"{vdur:.3f}", "-movflags", "+faststart", str(tmp)])
                tmp.replace(web)
        outs.append(web)
    pt = a.poster if a.poster is not None else max(0, vdur - 1.5)
    poster = od / f"{a.name}_포스터.jpg"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{pt:.3f}", "-i", str(master), "-frames:v", "1", "-q:v", "2", str(poster)])
    outs.append(poster)
    if a.timeline and Path(a.timeline).exists():
        tl = json.loads(Path(a.timeline).read_text())
        vo = [x for x in tl.get("vo", []) if not x.get("nosrt")]   # nosub(번인 제외)는 SRT 에 남긴다
        if vo:
            lines = []
            for i, x in enumerate(vo):
                end = x["end"] + 0.3
                if i + 1 < len(vo):
                    end = min(end, vo[i + 1]["start"] - 0.05)
                lines.append(f"{i + 1}\n{srt_time(x['start'] - 0.05)} --> {srt_time(end)}\n{x.get('sub') or x['text']}\n")
            srt = od / f"{a.name}.srt"
            srt.write_text("\n".join(lines), encoding="utf-8")
            outs.append(srt)

    # 검증
    print(f"{'파일':40s} {'크기':>8s}  규격")
    ok = True
    for f in outs:
        size = f"{f.stat().st_size / 1e6:.1f}MB"
        if f.suffix == ".mp4":
            v, au, fm = probe(f)
            I, LRA, TP = loud(f) if au else (None, None, None)
            spec = (f"{v.get('width')}x{v.get('height')} {v.get('r_frame_rate')} {v.get('pix_fmt')}/{v.get('color_range')} "
                    f"{v.get('nb_read_frames')}f {float(fm['duration']):.2f}s")
            if au:
                spec += f" | AAC {au.get('sample_rate')}Hz I {I} LUFS LRA {LRA} peak {TP}dBFS"
            flags = []
            if v.get("pix_fmt") != "yuv420p" or v.get("color_range") not in ("tv", None):
                flags.append("색 범위(yuv420p/tv 아님)")
            if au and I is not None and not (-15.5 <= I <= -12.5):
                flags.append(f"음량 {I} LUFS(목표 -14)")
            if au and TP is not None and TP > -0.9:
                flags.append(f"피크 {TP}dBFS(목표 ≤ -1)")
            if flags:
                ok = False
            print(f"{f.name:40s} {size:>8s}  {spec}" + ("  ✗ " + ", ".join(flags) if flags else "  ✓"))
        else:
            print(f"{f.name:40s} {size:>8s}")
    print("모든 산출물:\n" + "\n".join(f"  {f.resolve()}" for f in outs))
    if not ok:
        print("✗ 규격 문제가 있다 — 위 표시를 확인할 것")


if __name__ == "__main__":
    main()
