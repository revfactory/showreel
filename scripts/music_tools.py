#!/usr/bin/env python3
"""음악 도구: 스펙 → ElevenLabs composition plan, 생성된 음악 분석(템포·히트·에너지), 길이 맞춤.

사용법
  music_tools.py plan audio/music/spec.json [--out audio/music/plan.json]
      synth_music.py 와 같은 스펙(duration·mood·bpm·sections·events)으로 ElevenLabs Music 용 composition_plan 을 만든다.
      → eleven.py music audio/music/music.mp3 --plan audio/music/plan.json
  music_tools.py analyze audio/music/music.mp3 [--out audio/music/analysis.json]
      템포·박·다운비트·강한 히트·0.5초 에너지 곡선. ElevenLabs Music 은 섹션 길이를 정확히 지키지 않는다(대개 4마디 프레이즈로 수렴)
      → 생성 뒤 반드시 분석하고, 장면 경계를 실제 히트에 맞춘다(timeline.py --music-analysis 로 music.hitN 큐가 생긴다).
  music_tools.py splice in.mp3 out.wav --segments 0-3.9,7.78-19 [--snap analysis.json] [--xfade 0.006]
      구간을 이어 붙인다. 생성된 곡의 드롭이 늦게 오면 빌드업 끝 몇 박 뒤에 드롭 구간을 붙여 원하는 시각으로 당긴다.
      --snap 을 주면 경계를 가장 가까운 박에 맞춘다. 경계는 같은 박 위상(예: 마디 시작끼리)에서 자를 것.
  music_tools.py fit in.mp3 out.wav --dur 60 [--fade 2.5]
      길이 차이가 6% 이내면 템포를 미세 조정(atempo), 아니면 자르거나 채운 뒤 끝을 페이드. 소스 레벨 -16 LUFS.

스펙의 sections[].energy(0~1)는 plan 에서 문장으로 바뀐다. sections[].style 에 직접 묘사를 더할 수 있다(영어 권장).
곡 전체의 성격을 무드 4종(cinematic·pulse·soft·playful) 밖에서 정하려면 "global_styles": ["...", ...] 를 쓴다.
  이때 무드의 기본 문구 대신 global_styles 가 쓰이고(필요하면 "negative_styles" 로 제외할 것도 지정), 에너지 문장은 장르 중립 표현을 쓴다.
  "mood" 는 synth_music.py 대체 경로용으로 남겨 둔다.
주의: 아티스트·작곡가·곡 이름("Hans Zimmer style" 등)은 저작권 필터에 걸려 400 으로 거부된다. 장르·악기·분위기로만 쓴다.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

MOOD_STYLES = {
    "cinematic": (["epic cinematic trailer score", "hybrid orchestral with modern pulse synths", "big taiko and orchestral percussion",
                   "majestic, inspiring, premium brand film", "instrumental", "high production value"],
                  ["vocals", "singing", "lyrics", "rap", "lo-fi", "comedy", "acoustic guitar", "cheesy"]),
    "pulse": (["modern cinematic electronic", "tech keynote energy", "driving synth pulse and arpeggios", "precise, confident, inventive",
               "instrumental", "high production value"], ["vocals", "singing", "lyrics", "rap", "lo-fi", "acoustic guitar", "comedy"]),
    "soft": (["emotional cinematic piano and strings", "warm, intimate, hopeful", "gentle build", "instrumental"],
             ["vocals", "singing", "lyrics", "drums heavy", "EDM", "comedy"]),
    "playful": (["upbeat playful pop instrumental", "bright plucks, claps and bells", "bouncy groove", "cute and cheerful", "instrumental"],
                ["vocals", "singing", "lyrics", "dark", "horror", "heavy distortion"]),
}


ENERGY_WORDS = {   # 무드마다 에너지 단계별 표현(테크 무드에 "full orchestra"가 들어가지 않게). neutral 은 global_styles 를 쓸 때
    "neutral": [["sparse and quiet", "minimal"], ["building tension"], ["driving", "full arrangement"], ["peak energy", "maximum energy"]],
    "cinematic": [["sparse and quiet", "minimal, atmospheric"], ["building tension", "restrained pulse"],
                  ["driving rhythm", "full arrangement"], ["epic climax", "powerful drums and full orchestra", "maximum energy"]],
    "pulse": [["sparse and quiet", "minimal synth texture"], ["building tension", "filtered pulse"],
              ["driving beat", "full arrangement"], ["peak energy", "big drop with punchy drums and bass", "maximum energy"]],
    "soft": [["sparse and quiet", "solo piano"], ["gentle build", "warm strings enter"],
             ["flowing", "full warm arrangement"], ["emotional peak", "soaring strings"]],
    "playful": [["light and sparse", "plucks only"], ["bouncy build", "claps enter"],
                ["groovy", "full bouncy arrangement"], ["peak energy", "big cheerful drop"]],
}


def energy_words(e, mood="cinematic"):
    w = ENERGY_WORDS.get(mood, ENERGY_WORDS["cinematic"])
    return list(w[0 if e < 0.25 else 1 if e < 0.5 else 2 if e < 0.75 else 3])


def cmd_plan(a):
    spec = json.loads(Path(a.spec).read_text())
    dur = float(spec["duration"])
    mood = spec.get("mood", "cinematic")
    if spec.get("global_styles"):          # 콘셉트가 정한 곡의 성격. 무드 기본 문구를 쓰지 않는다
        pos, neg = list(spec["global_styles"]), list(spec.get("negative_styles", ["vocals", "singing", "lyrics"]))
        ew = "neutral"
    else:
        pos, neg = MOOD_STYLES.get(mood, MOOD_STYLES["cinematic"])
        pos, neg = list(pos), list(neg) + list(spec.get("negative_styles", []))
        ew = mood
    if spec.get("bpm"):
        pos.append(f"{int(spec['bpm'])} BPM")
    if spec.get("key"):
        pos.append(f"{spec['key']} {'minor' if spec.get('minor', mood == 'cinematic') else 'major'}")
    pos += spec.get("styles", [])
    secs = sorted(spec.get("sections", [{"start": 0, "energy": 0.6}]), key=lambda s: s["start"])
    # 섹션은 3초 이상이어야 한다(API). 짧은 섹션은 앞 섹션에 합치되, 앞 섹션의 시작·이름은 그대로 두고
    # 에너지는 큰 쪽, 스타일은 이어 붙인다. 맨 앞 섹션이 짧으면 뒤 섹션과 합친다.
    def merge(a_, b_):
        m = dict(a_)
        m["energy"] = max(float(a_.get("energy", 0.5)), float(b_.get("energy", 0.5)))
        m["style"] = ", ".join(x for x in (a_.get("style"), b_.get("style")) if x)
        m["name"] = a_.get("name") or b_.get("name")
        return m
    merged = []
    for s in secs:
        s = dict(s)
        if merged and (s["start"] - merged[-1]["start"]) < 3.0:
            gap = s["start"] - merged[-1]["start"]
            if gap >= 1.8:   # 빌드업→드롭 구조를 살리려고 경계를 3초 지점으로 민다(뒤 섹션이 3초 이상 남을 때)
                if dur - (merged[-1]["start"] + 3.0) >= 3.0:   # 뒤 섹션들은 다음 차례에 같은 규칙으로 밀린다
                    print(f"  · '{s.get('name', s['start'])}' 경계를 {s['start']}s → {merged[-1]['start'] + 3.0:.2f}s 로 밂(섹션 최소 3초)"
                          " — 생성 후 analyze 로 실제 위치를 읽고 splice 로 맞출 것")
                    s["start"] = round(merged[-1]["start"] + 3.0, 3)
                    merged.append(s)
                    continue
            print(f"  · '{s.get('name', s['start'])}'({s['start']}s)가 앞 섹션과 3초 미만이라 합침")
            merged[-1] = merge(merged[-1], s)
            continue
        merged.append(s)
    while len(merged) > 1 and dur - merged[-1]["start"] < 3.0:
        last = merged.pop()
        print(f"  · 마지막 섹션 '{last.get('name', last['start'])}'이 3초 미만이라 앞 섹션에 합침")
        merged[-1] = merge(merged[-1], last)
    events = spec.get("events", [])
    if spec.get("bpm"):
        bar = 4 * 60 / float(spec["bpm"])
        off = [s for s in merged[1:] if abs(s["start"] / bar - round(s["start"] / bar)) > 0.1]
        if off:
            print(f"  ! 4마디({bar * 4:.2f}s)·1마디({bar:.3f}s) 경계에 있지 않은 섹션: " + ", ".join(f"{s['start']}s" for s in off)
                  + " — 음악은 대개 4마디 단위로 생성되므로 생성 후 analyze 로 실제 위치를 확인할 것")
    sections = []
    for i, s in enumerate(merged):
        st = s["start"]
        en = merged[i + 1]["start"] if i + 1 < len(merged) else dur
        local = energy_words(float(s.get("energy", 0.5)), ew) + ([s["style"]] if s.get("style") else [])
        lneg = []
        for ev in events:
            t = float(ev["t"])
            if abs(t - st) < 0.4 and ev["type"] in ("hit", "boom", "braam"):
                local.append("starts immediately with a massive hit on the first beat")
                lneg += ["slow intro", "fade in"]
            elif st + 0.4 <= t < en - 0.2 and ev["type"] in ("hit", "boom", "braam"):
                local.append(f"a big hit about {t - st:.1f} seconds into this section")
            if ev["type"] == "stop" and st < t <= en + 0.01 and abs(t - en) < 1.5:
                local.append("ends abruptly in silence")
            # 라이저는 끝(t)이 이 섹션 안이거나 끝 경계에 있으면 이 섹션에 붙인다
            if ev["type"] == "riser" and st < t <= en + 0.4:
                local.append("rising tension into the next section")
        if i == len(merged) - 1:
            local.append(spec.get("ending", "final big hit then long reverb ring out"))
        sections.append({"section_name": s.get("name") or f"Part {i + 1}", "positive_local_styles": local,
                         "negative_local_styles": lneg, "duration_ms": int(round((en - st) * 1000)), "lines": []})
    diff = int(round(dur * 1000)) - sum(x["duration_ms"] for x in sections)
    sections[-1]["duration_ms"] += diff
    plan = {"model_id": spec.get("model_id", "music_v1"),
            "composition_plan": {"positive_global_styles": pos, "negative_global_styles": neg, "sections": sections}}
    # 에너지 곡선 점검: 한 세기로 오래 이어지면 생성된 곡도 평평해진다(2분 곡에서 16~112초가 같은 세기로 나온 사례)
    span = [(float(m.get("energy", 0.5)), (merged[i + 1]["start"] if i + 1 < len(merged) else dur) - m["start"]) for i, m in enumerate(merged)]
    high = sum(d for e, d in span if e >= 0.75)
    if high > 0.5 * dur:
        print(f"  ! 에너지 0.75 이상 구간이 {high:.0f}s({high / dur * 100:.0f}%) — 곡이 평평해진다. 절정(≥0.9)은 전체의 25% 안으로, "
              "중간에 0.3~0.45 로 내려가는 브레이크다운을 하나 넣을 것")
    if dur >= 45 and not any(e <= 0.45 for e, _ in span[1:-1]):
        print("  ! 첫·마지막 섹션 사이에 0.45 이하로 내려가는 섹션이 없다 — 큰 히트 앞의 숨 고르기가 없으면 히트가 약하게 들린다")
    for x, y in zip(sections, sections[1:]):
        if x["positive_local_styles"][:2] == y["positive_local_styles"][:2] and not any(k in merged[sections.index(y)] for k in ("style",)):
            print(f"  ! '{x['section_name']}'과 '{y['section_name']}' 묘사가 같다 — 뒤 섹션 style 에 악기 변화를 적을 것"
                  "(예: 'strings drop out, only ticking pulse', 'add brass stabs and choir', 'half-time drums')")
    out = Path(a.out) if a.out else Path(a.spec).with_name("plan.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print(f"{out}: 섹션 {len(sections)}개 · " + " | ".join(f"{x['section_name']} {x['duration_ms'] / 1000:.1f}s" for x in sections))


def decode(path, sr=22050):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def refine_period(onset, ft, period):
    """박 주기를 곡 전체의 온셋에 맞춰 다듬는다. 근거가 모자라면 입력을 그대로 돌려준다.

    자기상관 피크는 1홉(23ms) 격자 위에 있어 보간해도 주기에 0.1~2ms 오차가 남고, 곡 끝까지 박을 찍으면 그 오차가 쌓인다
    (60초 125 BPM 곡에서 124.54 BPM 으로 읽어 끝 박이 169ms, 5분 120 BPM 곡에서 양 끝 박이 50~70ms 어긋난 사례).
    강한 온셋마다 후보 주기 P 에서의 위상 벡터 exp(2πi·t/P)를 더해 크기가 가장 큰 P 를 고른다. 곡 전체를 한꺼번에 보므로
    처음 추정이 조금 틀려 끝 박이 반 박 가까이 밀려 있어도 맞는 주기를 찾는다.
    """
    pk = np.flatnonzero((onset[1:-1] > onset[:-2]) & (onset[1:-1] >= onset[2:])) + 1
    pk = pk[onset[pk] > np.percentile(onset, 75)]
    if len(pk) < 16:
        return period
    dt = ft[1] - ft[0]
    y0, y1, y2 = onset[pk - 1], onset[pk], onset[pk + 1]
    den = np.where(y0 - 2 * y1 + y2 != 0, y0 - 2 * y1 + y2, -1.0)
    t = ft[pk] + np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5) * dt   # 포물선 보간으로 프레임보다 정밀한 시각
    w = y1 - np.median(onset)

    def coherence(P):   # 1·2·4배음: 오프비트(반 박)·16분 온셋은 박 주기에서는 서로 상쇄되지만 배음에서는 같은 위상에 모인다
        return np.stack([np.abs((w[None, :] * np.exp(2j * np.pi * m * t[None, :] / P[:, None])).sum(1)) for m in (1, 2, 4)])

    best = period
    for span, n in ((0.03, 601), (0.0006, 241)):      # ±3% 를 0.01% 간격으로 훑은 뒤 그 둘레를 더 잘게
        P = best * np.linspace(1 - span, 1 + span, n)
        best = float(P[int(np.argmax(coherence(P).sum(0)))])
    if coherence(np.array([best])).max() < 4 * np.sqrt((w ** 2).sum()):   # 무작위 위상의 기대 크기보다 뚜렷이 크지 않으면 그대로 둔다
        return period
    return best


def cmd_analyze(a):
    sr = 22050
    x = decode(a.file, sr)
    n, h = 2048, 512
    fr = np.lib.stride_tricks.sliding_window_view(np.concatenate([x, np.zeros(n)]), n)[::h]
    S = np.abs(np.fft.rfft(fr * np.hanning(n), axis=1))
    flux = np.maximum(0, np.diff(np.log1p(10 * S), axis=0)).sum(1)
    flux = np.concatenate([[0], flux])
    flux /= np.percentile(flux, 99.5) + 1e-9
    ft = (np.arange(len(flux)) * h + n / 2) / sr          # 프레임 시작이 아니라 창의 가운데 시각(0.046초 앞당겨지는 오차 보정)
    lowb = max(2, int(150 / (sr / n)))                     # 150Hz 아래 = 킥·베이스. 박 위상은 이 대역으로 잡는다(하이햇 오프비트에 끌리지 않게)
    lflux = np.maximum(0, np.diff(np.log1p(10 * S[:, :lowb]), axis=0)).sum(1)
    lflux = np.concatenate([[0], lflux])
    lflux /= np.percentile(lflux, 99.5) + 1e-9
    # 템포: 플럭스 자기상관(60~180 BPM)
    fl = flux - flux.mean()
    ac = np.correlate(fl, fl, mode="full")[len(fl) - 1:]
    lags = np.arange(len(ac)) * h / sr
    ok = (lags >= 60 / 180) & (lags <= 60 / 60)
    k0 = np.flatnonzero(ok)[np.argmax(ac[ok])]
    # 포물선 보간으로 1홉(23ms)보다 정밀하게
    if 0 < k0 < len(ac) - 1:
        y0, y1, y2 = ac[k0 - 1], ac[k0], ac[k0 + 1]
        den = y0 - 2 * y1 + y2
        k0 = k0 + (0.5 * (y0 - y2) / den if den != 0 else 0)
    period = k0 * h / sr
    bpm = 60 / period
    while bpm < 75:
        bpm *= 2
    while bpm > 165:
        bpm /= 2
    period = refine_period(2.0 * lflux + flux, ft, 60 / bpm)
    bpm = 60 / period
    # 위상: 박 격자 위 플럭스 합이 최대인 위상
    best, ph_best = -1, 0
    for ph in np.arange(0, period, 0.005):
        idx = np.round((np.arange(ph, ft[-1], period) * sr - n / 2) / h).astype(int)
        idx = idx[(idx >= 0) & (idx < len(flux))]
        sc = (2.0 * lflux[idx] + flux[idx]).sum()
        if sc > best:
            best, ph_best = sc, ph
    beats = np.arange(ph_best, ft[-1], period)
    # 다운비트: 4박 중 저역 에너지가 가장 큰 위치. 박 직후 0.1초의 평균으로 본다
    # (박 시각은 온셋 감지 특성상 10~25ms 이르게 잡혀, 박 프레임 한 장만 보면 킥·베이스가 오기 전이라 네 무리의 점수가 거의 같아진다)
    low = (S[:, : int(150 / (sr / n))] ** 2).sum(1)
    cl = np.concatenate([[0.0], np.cumsum(low)])
    i0 = np.searchsorted(ft, beats)
    i1 = np.maximum(np.searchsorted(ft, beats + 0.1), i0 + 1).clip(max=len(low))
    lb = (cl[i1] - cl[np.minimum(i0, len(low) - 1)]) / np.maximum(1, i1 - i0)
    sc4 = [lb[k::4].mean() if len(lb[k::4]) else 0 for k in range(4)]
    downbeats = beats[int(np.argmax(sc4))::4]
    # 강한 히트: 플럭스 피크(상위 3%, 0.25초 간격)
    thr = np.percentile(flux, 97)
    hits, last = [], -9
    w = int(0.08 * sr / h)
    for i in range(w, len(flux) - w):
        if flux[i] >= thr and flux[i] == flux[i - w:i + w].max() and ft[i] - last > 0.25:
            hits.append(round(float(ft[i]), 3))
            last = ft[i]
    rms = np.sqrt((fr ** 2).mean(1))
    hop_half = int(0.5 * sr / h)
    energy = [[round(i * h / sr, 2), round(float(20 * np.log10(rms[i:i + hop_half].mean() + 1e-9)), 1)] for i in range(0, len(rms), hop_half)]
    res = {"file": str(a.file), "duration": round(len(x) / sr, 3), "bpm": round(float(bpm), 2),
           "beats": [round(float(b), 3) for b in beats], "downbeats": [round(float(b), 3) for b in downbeats],
           "hits": hits, "energy": energy}
    out = Path(a.out) if a.out else Path(a.file).with_name("analysis.json")
    out.write_text(json.dumps(res, ensure_ascii=False))
    print(f"{out}\n길이 {res['duration']}s · 템포 {res['bpm']} BPM (1박 {period:.3f}s, 1마디 {period * 4:.3f}s) · 첫 다운비트 {downbeats[0] if len(downbeats) else 0:.2f}s")
    print("강한 히트: " + ", ".join(f"{t:.2f}" for t in hits[:40]))
    top = max(e[1] for e in energy)
    print("에너지(0.5초, ▁~█): " + "".join("▁▂▃▄▅▆▇█"[max(0, min(7, int((e[1] - top + 30) / 30 * 8)))] for e in energy))
    body = np.array([e[1] for e in energy if 5 <= e[0] <= res["duration"] - 5])
    if len(body) > 20:
        flat = float((body >= np.percentile(body, 95) - 3).mean())
        if flat > 0.6:
            print(f"! 곡의 {flat * 100:.0f}% 가 최대 세기에서 3dB 안이다 — 평평한 곡. 숨 고르기 구간을 splice 로 넣거나(조용한 프레이즈를 잘라 붙임), "
                  "gap 으로 정적을 만들거나, 섹션 대비를 키운 플랜으로 다시 생성할 것")


def cmd_splice(a):
    """구간을 골라 이어 붙인다. 드롭을 원하는 시각으로 옮기거나, 4마디를 빼서 길이를 맞출 때 쓴다."""
    segs = []
    for part in a.segments.split(","):
        x, y = part.split("-")
        segs.append([float(x), float(y)])
    if a.snap:
        an = json.loads(Path(a.snap).read_text())
        grid = np.array(an.get("beats") or [])
        if len(grid):
            end = float(an.get("duration", 1e9))
            def snap(t):   # 처음(0초 근처)과 끝은 그대로, 안쪽 경계만 가장 가까운 박으로
                if t < 0.3 or t > end - 0.3:
                    return t
                g = float(grid[np.argmin(np.abs(grid - t))])
                return g if abs(g - t) < 0.25 else t
            segs = [[snap(x), snap(y)] for x, y in segs]
    xf = a.xfade
    filt, labels = [], []
    for i, (x, y) in enumerate(segs):
        filt.append(f"[0:a]atrim={x:.4f}:{y:.4f},asetpts=PTS-STARTPTS[s{i}]")
    cur = "s0"
    for i in range(1, len(segs)):
        filt.append(f"[{cur}][s{i}]acrossfade=d={xf}:c1=tri:c2=tri[c{i}]")
        cur = f"c{i}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-filter_complex", ";".join(filt), "-map", f"[{cur}]",
                    "-ar", "48000", "-ac", "2", a.out], check=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out], capture_output=True, text=True)
    pos, lay = 0.0, []
    for x, y in segs:
        lay.append(f"원본 {x:.3f}–{y:.3f}s → 결과 {pos:.3f}s")
        pos += (y - x) - xf
    print(f"{a.out} {float(r.stdout):.3f}s\n  " + "\n  ".join(lay) + "\n→ 다시 analyze 해서 장면 경계를 맞출 것")


def cmd_gap(a):
    """음악만 잠깐 끊는다(정적 연출). ElevenLabs Music 은 플랜의 stop 을 무시할 때가 많아 생성 뒤 여기서 만든다.
    --at 에서 짧게 줄여 끊고 --until(다음 프레이즈의 첫 박)에서 다시 연다. 여러 번이면 '103.2-103.97,30-30.8'."""
    sr = 48000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.src, "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).copy()
    t = np.arange(len(x)) / sr
    g = np.ones(len(x), np.float32)
    for part in a.ranges.split(","):
        s, e = (float(v) for v in part.split("-"))
        fo, fi = a.fade_out, a.fade_in
        m = (t >= s - fo) & (t < s)
        g[m] = np.minimum(g[m], (s - t[m]) / fo)
        g[(t >= s) & (t < e)] = 0
        m = (t >= e) & (t < e + fi)
        g[m] = np.minimum(g[m], (t[m] - e) / fi)
    x *= g[:, None]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", a.out],
                   input=x.tobytes(), check=True)
    print(f"{a.out}: 끊은 구간 {a.ranges} (줄임 {a.fade_out * 1000:.0f}ms · 다시 열기 {a.fade_in * 1000:.0f}ms)")


def cmd_fit(a):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.src], capture_output=True, text=True)
    got = float(r.stdout.strip())
    want = a.dur
    tempo = got / want
    filt = []
    if abs(tempo - 1) <= 0.06 and abs(tempo - 1) > 0.004:
        filt.append(f"atempo={tempo:.5f}")
    filt += [f"apad=whole_dur={want:.3f}", f"atrim=0:{want:.3f}", f"afade=t=out:st={max(0, want - a.fade):.3f}:d={a.fade:.3f}",
             "loudnorm=I=-16:TP=-1.5:LRA=11"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-af", ",".join(filt), "-ar", "48000", "-ac", "2", a.out], check=True)
    print(f"{a.out}: {got:.2f}s → {want:.2f}s ({'atempo ' + format(tempo, '.4f') if filt[0].startswith('atempo') else '자르기/채우기'})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan"); p.add_argument("spec"); p.add_argument("--out"); p.set_defaults(fn=cmd_plan)
    p = sp.add_parser("analyze"); p.add_argument("file"); p.add_argument("--out"); p.set_defaults(fn=cmd_analyze)
    p = sp.add_parser("splice"); p.add_argument("src"); p.add_argument("out"); p.add_argument("--segments", required=True)
    p.add_argument("--xfade", type=float, default=0.006); p.add_argument("--snap"); p.set_defaults(fn=cmd_splice)
    p = sp.add_parser("fit"); p.add_argument("src"); p.add_argument("out"); p.add_argument("--dur", type=float, required=True)
    p.add_argument("--fade", type=float, default=2.5); p.set_defaults(fn=cmd_fit)
    p = sp.add_parser("gap"); p.add_argument("src"); p.add_argument("out"); p.add_argument("ranges", help="시작-끝[,시작-끝…] 초")
    p.add_argument("--fade-out", type=float, default=0.06); p.add_argument("--fade-in", type=float, default=0.03); p.set_defaults(fn=cmd_gap)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
