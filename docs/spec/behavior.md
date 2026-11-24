# Measured behavior (clean-room spec)

Everything here comes from rendering audio through the reference plugin (an AU, hosted by
`pedalboard`) and measuring what came out. Nobody read, disassembled or inspected its binary. The
DSP is written from this document and from `analysis/model.py`, the numpy reference model that
this document describes.

Knobs are 0..1 with defaults Fat 0, Color 0, Gain 0.5. Measurements were taken at 48 kHz unless
noted otherwise.

## Block diagram

```
in L/R -> bell(color) -> HPF ~30 Hz -> HPF ~20 Hz -> x drive(fat, gain)
       -> stereo-linked peak limiter(threshold depends on fat) -> hard clip +-0.989 -> out
```

- Every stage is per-sample. The processing adds no latency (0 samples) and does no oversampling.
- One gain computer is shared by both channels; the channels are filtered independently.

## Laws

| Stage | Law | How it was found |
|---|---|---|
| Drive | `drive_dB = 39*fat + 72*gain - 35`. The defaults give +1.0 dB. | Low-level sine gain over 1-D knob sweeps |
| Bell | RBJ peaking EQ, `+8*color` dB, bandwidth 1.8928 octaves (constant). The centre frequency comes from `BELL_LUT` (46 Hz at 0.1, 757 Hz at 0.5, 6.72 kHz at 1.0) and is interpolated in log-frequency. Below 0.1 it is clamped, because the bell is under 0.8 dB there. | ESS frequency response fitted every 0.02 of color |
| HPF | Two RBJ high-pass biquads near 30 Hz and 20 Hz (Q ≈ 0.65–0.73). These also block DC. The corners shift slightly with sample rate, so `HPF_BY_SR` holds a fitted pair per rate (48 kHz: 29.9627 Hz Q 0.6684 and 20.1030 Hz Q 0.6747). Unlisted rates use the 48 kHz pair. | Time-domain fit on sub/kick/bass clips at each rate. Linear null is −55 dB at 192 kHz, and −66 to −79 dB at the other rates |
| Limiter | `env` is a one-pole on `max(abs L, abs R)` with attack 2.539 ms and release 29.269 ms. Those times hold at 48 kHz only: the coefficients are fixed in samples, so at 96 kHz they are half as long. The gain is `min(1, (T/env)^0.926)`, where `T_dB = 0.458 + 4.883*fat`. | Steady gain reduction is ~0.9 dB/dB. A Fat/Gain split at equal drive moved T by 5 dB per unit of Fat and 0 per unit of Gain. Release is linear in dB at 0.224 dB/ms. All five constants were then fitted by minimax null |
| Clip | Hard clip at ±0.989. Tops are flat and transitions take one sample. | Output never exceeds 0.989 |
| Params | Each knob is smoothed by a one-pole with τ = 10 ms (t50 6.9 ms, t90 23 ms, the same up and down). After a reset the original ramps from the defaults. | Automated knob steps |

## Verdicts on the Splice article's claims

- **"Fatness: up to +30 dB input boost plus saturation"**
  - *Mostly true.* Fatness boosts by +39 dB over its range.
  - It also raises the limiter threshold by 4.9 dB, so high Fat lets more peak through into the hard clip.
- **"Color reshapes the harmonic balance; more is brighter"**
  - *True in effect.* The mechanism is a bell placed before the drive. It sweeps from 46 Hz to 6.7 kHz and gains up to +8 dB, so the region it boosts is the one that saturates first.
  - The shaping itself is odd-symmetric. Harmonics are odd only; at 1 kHz with Fat 1 and Color 0.5 they measure H3 −11.2, H5 −19.6 and H7 −31 dBc.
- **"Gain is the output level"**
  - *False.* Gain is drive applied before the limiter and clip, spanning −35 to +37 dB.
  - At low drive it behaves like an output level. Once the signal is limiting, it mostly adds more saturation.
- **"Clip indicator"**: this is a GUI element, so it was not measurable from audio. The output ceiling is 0.989 (−0.1 dBFS).

## Quirks (copied)

- **Sample rate.**
  - The bell tracks the sample rate; its response is the same at every rate.
  - The HPF corners move slightly from rate to rate. This is copied per rate with `HPF_BY_SR`.
  - The limiter attack and release are fixed in samples at their 48 kHz values. With limiter times in ms instead, the 96 kHz null was −13.7 dB; with them in samples it was −26.6 dB (F1 C1 G1).
- **Ramp after reset.** After a reset, the knobs ramp from their defaults (0 / 0 / 0.5) with the 10 ms smoother. At F0 G0 the first ~20 ms are therefore up to +36 dB louder than steady state.
- **Aliasing.** The original aliases heavily: a 9 kHz tone leaves −10 dB of non-harmonic content at 48 kHz. Ours matches it, because neither oversamples.

### Not copied

- **44.1 kHz onset burst.** Hosted at 44.1 kHz, the original sometimes boosts the first ~20–50 ms after a reset, or after long silence, by up to 18×. How much depends on how long the silence was, and not monotonically. It never happens at 48, 88.2, 96 or 192 kHz. It looks like host or AU state rather than DSP, so there is no model to copy. `compare.py` skips each clip's first 200 ms.

## Match results (`analysis/compare.py <original> <our VST3>`)

The table covers 72 clips:
- 8 synthesized: kick, 808, saw bass, supersaw, snare, hats, pad, 261 Hz sine.
- 40 FL Studio factory samples.
- 24 song clips: 8 CC BY songs × 3. The genres are funk, hip-hop, rock, jazz, rap, electronic, orchestral and ambient.

The run covers 44.1, 48, 88.2, 96 and 192 kHz. Our plugin is pre-rolled 250 ms. The first 200 ms are skipped (600 ms at 44.1 kHz, because of the onset burst).

Null is phase cancellation: the RMS of `original − ours` over the RMS of the original. ΔLUFS is ungated K-weighted loudness. Each cell is the worst value across all five rates.

| Preset (F/C/G) | Worst null | Median null | Worst ΔLUFS | Worst 1/3-oct |
|---|---|---|---|---|
| F55 C20 G50 (Splice: bass, leads) | −29.8 dB | −35.0…−35.6 dB | 0.18 | 0.67 dB |
| F90 C35 G50 (Splice: 808) | −31.8 | −39.3…−39.7 | 0.13 | 0.62 |
| F8 C10 G50 (Splice: master) | −28.3 | −45.8…−51.7 | 0.27 | 0.53 |
| F100 C100 G100 | −24.4 | −27.0…−27.4 | 0.26 | 1.61 |
| F0 C0 G100 | −30.2 | −35.3…−35.8 | 0.20 | 0.69 |
| F100 C0 G0 | −41.8 | −51.6…−59.0 | 0.04 | 0.08 |
| F30 C70 G75 | −30.4 | −37.1…−37.7 | 0.18 | 0.79 |

**Pass criteria:**
- Splice presets: null ≤ −25 dB, LUFS within 0.3, every 1/3-octave band within 20 dB of the peak matches to ±1 dB.
- Extremes: null ≤ −20 dB.

## Model fitting log

Each step lists the hypothesis, then the worst null it reached on the fit set.

1. **Hard clip; filters magnitude-fitted from the ESS.** The null at low drive was −20 dB, so the phase was wrong.
2. **HPFs from a complex fit of a noise system ID.** Low drive improved to −65.6 dB. Driven material reached only −7…−13 dB.
3. **Topology search, varying where the bell and HPFs sit relative to the clip, linked vs independent.** Every filter before the clip, linked, was best, but driven material still sat at −10 dB.
4. **Scatter of output against the linear pre-clip signal.** Small samples are attenuated whenever peaks are large, which means a dynamic gain stage sits before the clip.
5. **RMS limiter, linked by max.** Driven material improved to −16…−28 dB.
6. **Peak (abs) detector with a ratio exponent.** Fit cases reached −31.8 dB, but high-Color and high-Gain held-out clips only reached −17…−26.
7. **Placement variants: bell, HPF or drive after the limiter.** All were worse; the original order was confirmed.
8. **Fat/Gain split test at equal drive.** It showed the threshold depends on Fat and not on Gain. With `T = T0 + Tf*fat`, every fit case reached ≤ −32.6 dB.
9. **Synthetic saw bass at F90 still failed (−23.5 dB).** Re-optimizing with the saw in the fit set left every case ≤ −36.3 dB. These are the final constants.

**Remaining error** (extremes at −26 to −30 dB): probably detector details such as hold time or log-domain smoothing. It is not worth chasing further against the −25 dB criterion.
