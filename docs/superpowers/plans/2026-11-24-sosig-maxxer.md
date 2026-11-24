# Sosig Maxxer: clean-room clone of a reference fattener plugin

## Context
The user wants a free, open-source plugin that matches the audible behavior of the reference fattener plugin (v1.4.1) (in `sosig-maxxer/plugins/`). It ships as VST3 + CLAP for Ableton and FL Studio on macOS and Windows, and for Linux hosts (Bitwig, Reaper, Ardour; Ableton and FL have no Linux builds). It is built from black-box audio measurement only, never from the original's code.

**Known inputs:**
- `SYParameters.txt`: `Fattness`, `Color` and `Gain`, all 0–1, with defaults 0/0/0.5. No factory presets.
- Splice blog (2014) claims, which are hypotheses for measurement to confirm or refute:
  - Fatness = up to +30 dB input boost plus saturation.
  - Color = reshapes the harmonic balance; more of it gives more high harmonics and a brighter sound.
  - Gain = output level, for level-matching.
  - There is a clip indicator.
  - Typical settings: bass and leads at F55/C20, 808 at F90/C35, master bus at F8/C10. A 261 Hz sine demo.
- FL Studio 2026 is now installed. It's used for A/B listening and host checks; automated measurement still runs headless through Python `pedalboard`.

The existing task-level plan at `sosig-maxxer/docs/superpowers/plans/2026-11-24-sosig-maxxer.md` gets rewritten to match this file as the first execution step.

## Decisions
- **Rust + nih-plug:** same speed as C (both compile through LLVM); one codebase; `cargo xtask bundle` produces VST3 + CLAP. License GPL-3.0.
- **Clean room:** no decompiling, disassembling or binary inspection. DSP is written only from `docs/spec/behavior.md` plus measurement data. Our own name, art and copy; no original product or vendor names anywhere we ship.
- **GUI:** our own cartoon sausage whose face goes from smiling to gritted teeth as Fat rises (the user's request). Black/white/greys only. We draw it ourselves in a different style, which keeps the look distinct from the original's.
- **Hosting:** Forgejo at `git.popat.org`. CI copies the `agenttux/shoo` patterns.

## Tasks

### 1. Repo + analysis harness
- `git init`. `.gitignore` covers `plugins/`, `target/`, `analysis/data/ours/`, `analysis/corpus/local/` and `.venv/`.
- Python venv: `pedalboard numpy scipy soundfile matplotlib pyloudnorm pytest`.
- `analysis/signals.py`:
  - sine
  - ESS (exponential sine sweep) + inverse
  - level steps
  - bursts
  - impulse
  - two-tone: SMPTE 60 Hz + 7 kHz 4:1, and CCIF 19 + 20 kHz
  - stereo cases: L-only, mono, anti-phase
  - DC-offset / asymmetric pulse
- `analysis/render.py`:
  - `load(path)`
  - `render(plugin, audio, sr, fat, color, gain, tail_s)`
  - `render_automated(plugin, audio, sr, schedule)`: chunked processing with `reset=False`, changing params between chunks, so smoothing and zipper behavior can be measured.
- Tests: `analysis/tests/test_signals.py`.

### 2. Deep measurement of the original (expanded per user)
`analysis/measure.py`, with each function unit-tested against synthetic systems of known answer (delay, gain, `tanh`, `x + a·x²`, one-pole envelope follower).

**Static / tonal**
- Latency.
- Static in→out curve: −60…+6 dBFS in 1 dB steps. This tests the "+30 dB boost" claim and finds the knee and ceiling.
- Frequency and phase response at 3 drive levels (ESS at −36/−18/−6 dBFS).

**Harmonic**
- Farina H2–H9 vs Color.
- Harmonics vs input frequency (50, 100, 261, 1k, 5k Hz), to catch pre/post-emphasis filtering around the shaper.
- IMD from SMPTE and CCIF.
- Aliasing at 5–15 kHz tones, which reveals oversampling.

**Time / memory**
- Attack and release from bursts.
- Memoryless check: identical sine after silence vs after loud material.
- DC and asymmetry handling.
- Param-smoothing time from `render_automated`.

**Stereo**
- Crosstalk, linked vs independent processing, mid/side.

**Mapping**
- 1-D sweeps of each knob in 0.01 steps (others at default), to fit the exact knob→dB and knob→curve mappings.

**Grid**
- Fat × Color in 0.1 steps (121) × Gain {0, .25, .5, .75, 1} = 605 configs at 48 kHz.
- Spot checks of 9 configs at 44.1, 96 and 192 kHz.

**Instrument corpus (new)** in `analysis/corpus/`:
- **Synthesized and committed** (license-free, deterministic, from `analysis/corpus/make.py`): kick, 808 with long tail, saw/square electro bass, supersaw lead, snare, hi-hat loop, pad, 261 Hz sine (Splice demo).
- **Local, gitignored** in `analysis/corpus/local/`: these are Image-Line licensed, so they're used for measurement only and never committed or shipped. `analysis/corpus/fetch_fl.sh` copies a curated set from `/Applications/FL Studio 2026.app/Contents/Resources/FL/Data/Patches/Packs/`:
  - `Drums/Kicks`, `Drums/Snares`, `Drums/Hats`, `Drums (ModeAudio)/Kicks` (several each)
  - `Instruments/Bass`, `Instruments/Keyboard`, `Instruments/Guitar`
  - `Vocals/*` (Laurie Webb + VOC phrases)
  - `Loops/DL *` (15 full drum loops, standing in for the drum bus/master test)
  - The script writes a `manifest.json` (path, sha256, category) so runs are reproducible.
  - The user can add their own Splice WAVs to the same folder.

**Music metrics** (`measure_music.py`, per clip × named preset + a 5×5 grid):
- integrated LUFS and true peak
- crest factor
- 1/3-octave spectral difference
- transient envelope correlation
- level-aligned null residual (dB)

**Named presets:** Splice settings F55/C20, F90/C35 and F8/C10, plus extremes.

**Outputs:**
- `analysis/data/original/*.json` + plots.
- `docs/spec/behavior.md`: every finding with numbers, an explicit verdict on each Splice claim, and a proposed block diagram + fitted curves, plus a "Model fitting log" section.

### 3. Rust scaffold
- nih-plug, pinned by commit; confirm the VST3 binding license.
- `SosigParams`: ids `fat`/`color`/`gain`, display `Fat`/`Color`/`Gain`, 20 ms smoothing (tuned to the measured smoothing).
- `src/dsp/mod.rs` `Fattener` with no nih-plug imports: `new(sr)`, `reset(sr)`, `latency_samples()`, `process_frame(l, r, fat, color, gain) -> (f32, f32)`, `peak_out() -> f32` (feeds the clip LED and face meter via an atomic).
- Layouts 2→2 and 1→1.
- The harness loads our bundled `.vst3`, so `sweep.py` and `compare.py` run on both plugins unchanged.

### 4. DSP model + match loop
- Rust invariant tests in `tests/dsp.rs`:
  - block-size invariance
  - no click on param jumps
  - +12 dBFS square stays finite and bounded
  - DC decays
  - silence tail reaches exact 0 (denormal flush)
  - 48k/96k harmonic match within 0.5 dB
- `analysis/compare.py`, which exits non-zero on failure.

**Thresholds (my call):**
- Static curve and FR: ±0.5 dB.
- H2–H7: ±1.5 dB above −60 dBc.
- Envelope: ±15%.
- Music: LUFS ±0.3 LU, 1/3-octave ±1 dB, null residual ≤ −25 dB on the Splice presets.

**Loop:** iterate the model until `compare.py` passes. Then render corpus A/B pairs to `analysis/data/listen/` with randomized "A"/"B" labels plus a key file, so the user can blind-test in FL Studio. This is a human gate.

### 5. GUI: monochrome cartoon sausage
- **Icon:**
  - Browse the Noun Project in the built-in browser and shortlist about 3 sausage icons for the user to pick.
  - The user downloads the SVG; downloads need their OK, and NounPro or CC BY terms apply.
  - Commit it to `assets/sausage.svg`.
  - Attribution goes in the About overlay, README and `assets/ATTRIBUTION.md` when CC BY.
- **Render:** `nih_plug_egui` + `egui_extras` SVG (resvg). The icon is tinted to the palette. The face is drawn procedurally on top with `egui::Painter`.
- **Googly eyes:**
  - White circles with black outlines and black pupils.
  - Pupils driven by a damped spring sim fed by output level, so they wobble on transients.
  - Eyelids lower slightly as Fat rises.
- **Mouth:**
  - A cubic Bézier morphing with smoothed Fat. 0 = wide smile; around 0.5 = flat/strained; 1 = gritted, a rounded rect with vertical tooth lines.
  - Teeth fade in from about 0.6.
  - Optional brow lines at high Fat.
- **Layout:** sausage on top, 3 knobs below (Fat, Color, Gain) with value readouts. Double-click resets. Clip LED (white→black flash) when output exceeds 0 dBFS.
- **Palette:** `#000`, `#fff` and 3 greys (`#222`, `#777`, `#ccc`) only. Use a monochrome font such as bundled Inter or the egui default.
- Window 420×360, resizable.
- **Test:** pure `face_shape(fat) -> FaceGeom` unit-tested (smile curvature > 0 at 0, < 0 at 1, teeth count 0 at 0 and > 0 at 1). Then a manual check in FL Studio.

### 6. Forgejo CI + release (modeled on `agenttux/shoo`)
- **Setup:** the repo is already created on `git.popat.org` by the user. Confirm the owner/URL with `git ls-remote`, then add it as `origin`. `RELEASE_TOKEN` secret is optional; `github.token` is the fallback.
- **`.forgejo/workflows/ci.yml`** (`runs-on: docker`):
  - Install the apt X11/GL/ALSA/JACK deps that nih-plug needs, and rustup with clippy and rustfmt.
  - `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, and Python `pytest analysis/tests` (pure-math tests only; no plugin rendering on Linux).
  - Cache restore/save exactly as in shoo, saved from `main` only.
  - Bundle the Linux build and run `clap-validator` and `pluginval` (headless via `xvfb-run`).
- **`.forgejo/workflows/release.yml`**, on push to `main`; no caches; prebuilt tools pinned by sha256:
  - `version`: `uses: https://git.popat.org/agenttux/forgejo-actions/next-version@v1`, then `scripts/release.sh release`.
  - `linux`: `cargo xtask bundle sosig_maxxer --release`, tar the `.vst3` + `.clap`, upload.
  - `windows`: cross-compile with `cargo-xwin` (built from source, pinned version). Run `eval "$(cargo xwin env --target x86_64-pc-windows-msvc)"`, then `cargo xtask bundle sosig_maxxer --release --target x86_64-pc-windows-msvc`, zip, upload.
- **`scripts/release.sh`:** copy shoo's, with `set-version` changed to stamp only the root `Cargo.toml`.
- **`scripts/publish-mac.sh` + `.githooks/pre-push`:** copy shoo's, with these changes:
  - build `cargo xtask bundle-universal sosig_maxxer --release` (x86_64 + arm64)
  - ad-hoc `codesign --force --deep -s -`
  - zip and upload `sosig-maxxer-<ver>-macos-universal.zip`
- **README:** install paths per OS; mac `xattr -dr com.apple.quarantine` note.

## Verification
- `pytest analysis/tests -v`: all measurement functions match synthetic known systems.
- `cargo test`: DSP invariants + `face_shape` tests.
- `python analysis/sweep.py` on both plugins, then `python analysis/compare.py analysis/data/original analysis/data/ours` exits 0, including the music metrics.
- Blind A/B in FL Studio on corpus renders. The user can't reliably pick the original on the Splice presets.
- Forgejo CI is green; pluginval + clap-validator pass on Linux. A release has Linux, Windows and mac artifacts attached.
- **Manual host check:**
  - FL Studio 2026 on mac: load, automate all 3 knobs, the face animates, save/reopen, bounce.
  - Ableton, and Windows FL, when available.
  - Reaper or Bitwig on Linux.
