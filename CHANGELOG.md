# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Rebuilt the workflow around the core request ("당신이 얼마나 놀라운 모션 그래픽 디자이너인지 보여주는 … 이력서용 쇼릴 처럼요. 전력을 다해요."). `SKILL.md` now opens with what each part of that request demands from the result.
- Removed the default mood (dark background, gold accent, letterbox, grain, HUD) and the mood presets. Art direction (medium, palette, type, motion character, texture) is decided per project and per segment in `concept.md`. `design.md` lists the template look to avoid unless a concept calls for it.
- Questions are limited to facts only the user knows (subject, must-have facts, asset locations). Mood, length, aspect ratio, narration and images are Claude's decisions; a self-showreel request asks nothing.
- Narration is no longer on by default; showreels are carried by music and picture.
- New concept step: three or more candidates scored on the same criteria (`references/brief.md`).
- New critique loop after every draft: eight questions (including "could the next segment be predicted?"), keep / fix / rebuild per segment, logged in `qa/critique_NN.md`; the weakest segment is rebuilt rather than tweaked (`references/qa.md`).
- `story.md` adds a showreel section and drops formulaic copy rules; `techniques.md` is framed as a code library, not a menu.
- `new_project.py` creates an empty `scenes.js` and copies the engine sample to `reel/_example_scenes.js` (not loaded). `index.html` colour tokens are grey placeholders.

### Added

- WebGL2 shader and three.js examples, verified in the renderer with sub-frame motion blur, and a pattern for precomputed simulations (`references/engine.md`).
- Splitting segments across subagents with a contract that carries each segment's art direction.
- Eval `self-showreel-60s-core` with the core request verbatim.
- `new_project.py --fonts "Family:wght@400;900"` adds Google Fonts families (OFL) beyond the default set; the list is kept in `reel/fonts/.extra_fonts` across reruns.
- `music_tools.py plan` accepts `global_styles` / `negative_styles` / `ending` in the music spec, so a concept can set the genre instead of the four fixed mood phrases (`mood` stays for the synth fallback).

### Fixed

- `music_tools.py analyze` took the tempo from one autocorrelation peak on the 23 ms hop grid and carried that period to the end of the track, so beats drifted: a 60 s 150 BPM click track read as 150.60 BPM with its last beats 0.2 s off, and a 180 s 90 BPM track drifted 0.33 s. The period is now refined against the phase of every strong onset across the whole track (1st, 2nd and 4th harmonics, so off-beat hi-hats do not cancel the kicks), and downbeats compare the low-band energy in the 0.1 s after each beat instead of one frame. On synthetic tracks from 90 to 150 BPM (60 s and 180 s, with and without off-beat hats) the largest beat error fell from 33–334 ms to 25–27 ms; the remaining constant offset comes from the unchanged phase search.
- `timeline.py` resolved scene, narration and SFX times before reading the music analysis, so `scenes` could not use the `bar9` / `music.hit2` cues its own header documents. The music analysis is now read first; output for inputs that did not use those cues is unchanged.
- `timeline.py` now writes a `scene.<id>.end` cue for scenes without an explicit `end` (next scene's start, or the video end). Before, `cue('scene.<id>.end')` returned 0 and the scene never showed.
- `qa_check.py` counted every frame brighter than 225 as a blown-out white frame, so designed light backgrounds failed QA. It now counts only short bright spikes (< 0.3 s) between darker frames and lists longer light runs as information.
- `finish.py` lowered the share file's audio peak once without re-measuring; re-encoding could leave it at −0.6 dBFS. It now re-measures and repeats up to three times until true peak ≤ −1.0 dBFS.
- `finish.py` built the share file by re-encoding the master's 320 kb/s AAC, which raised its true peak (−1.9 → −0.6 dBTP on a −14 LUFS mix), and each peak-correction pass re-encoded the previous AAC again, so the reductions compounded. Share files came out at −17.5 LUFS (normal mix) and −18.5 LUFS (a −12.6 LUFS mix) while the master was correct. The share audio is now encoded once from the `--audio` mix, and a correction pass re-encodes from that mix with the accumulated gain (−14.2 and −14.4 LUFS on the same inputs).
- `eleven.py music` drops `--seed` with a warning when used with `--prompt` (the API returned 422); `eleven.py sfx` now flags near-silent results (peak ≤ −24 dB) like `sfx-kit`.
- `mix.py` measured "SFX vs music" in the 0.3 s after `t` even for `align: end` effects, which end at `t`, and printed −45 to −155 dB. It now measures the 0.3 s before `t` for those.
- `SKILL.md` now says scene boundaries also go half a frame before the cue; integer-second boundaries blended neighbouring segments in `--sub 4` renders.
- `motion_check.py` now runs the same photosensitive flash check as `qa_check.py`, so drafts catch flash failures before the final render (a comparison run found 25 flashes in one segment only at the master QA).
- `motion_check.py` no longer recommends specific devices (`FX.floor`, Ken Burns, level bars) for frozen stretches.

## [1.0.0] - 2026-10-08

First public release.

### Added

- `SKILL.md` workflow from brief to delivery: preflight, one-time brief, research, storyboard and script, audio first, images, scenes, draft review loop, final render and mix, automated QA and delivery report.
- Deterministic HTML motion engine (`assets/engine/`) and Playwright renderer with sub-frame motion blur, resumable chunks and parallel workers.
- ElevenLabs tooling: TTS with per-line regeneration and STT verification, Music composition plans, SFX kit, voice listing.
- Music analysis and splicing, and a NumPy music/SFX synthesizer as a fallback.
- Mixer with speech-band ducking, per-line narration-vs-bed report and two-pass loudness normalization to -14 LUFS.
- Automated QA: spec, loudness, dark segments, photosensitive flashes, frozen frames, low motion and STT of the final mix.
- Reference guides for brief, story, audio, images, design, engine, 22 motion techniques and QA.
- Evaluation prompts in `evals/evals.json`.

### Changed

- Narration reverb is off by default. `mix.py --hall` now sets the actual wet/dry ratio on speech (0.06 = -24 dB), uses a 1.4 s hall with a 30 ms pre-delay and a soft onset, and reports the reverb tail after each phrase (✗ above -28 dB). The previous 2.4 s hall at `--hall 0.12` produced a -22.8 dB tail and sounded echoey.

[Unreleased]: https://github.com/revfactory/showreel/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/revfactory/showreel/releases/tag/v1.0.0
