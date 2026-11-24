// nih_export_vst3! trips this future-compat lint inside the upstream macro.
#![allow(semicolon_in_expressions_from_non_local_macros)]
use nih_plug::prelude::*;
use std::num::NonZeroU32;
use std::sync::Arc;

pub mod dsp;
pub mod editor;

#[derive(Params)]
pub struct SosigParams {
    #[persist = "editor-state"]
    editor_state: Arc<nih_plug_egui::EguiState>,
    #[id = "fat"]
    pub fat: FloatParam,
    #[id = "color"]
    pub color: FloatParam,
    #[id = "gain"]
    pub gain: FloatParam,
}

/// dB of drive per unit of Gain travel (see docs/spec/behavior.md, Drive).
pub const GAIN_DB: f32 = 72.0;

pub(crate) fn knob(name: &str, default: f32) -> FloatParam {
    FloatParam::new(name, default, FloatRange::Linear { min: 0.0, max: 1.0 })
        .with_value_to_string(formatters::v2s_f32_percentage(0))
        .with_string_to_value(formatters::s2v_f32_percentage())
        .with_unit("%")
}

impl Default for SosigParams {
    fn default() -> Self {
        Self {
            editor_state: editor::default_state(),
            fat: knob("Maxx", 0.0),
            color: knob("Color", 0.0),
            // shown as the dB it adds relative to the default (72 dB per unit of travel, measured),
            // to 0.1 dB like the original's readout
            gain: FloatParam::new("Gain", 0.5, FloatRange::Linear { min: 0.0, max: 1.0 })
                .with_value_to_string(Arc::new(|v| {
                    format!("{:+.1}", (GAIN_DB * (v - 0.5) * 10.0).round() / 10.0 + 0.0)
                }))
                .with_string_to_value(Arc::new(|s| {
                    let db: f32 = s.trim().trim_end_matches("dB").trim().parse().ok()?;
                    Some((db / GAIN_DB + 0.5).clamp(0.0, 1.0))
                }))
                .with_unit(" dB"),
        }
    }
}

pub struct SosigMaxxer {
    params: Arc<SosigParams>,
    dsp: dsp::Fattener,
    /// Max |out| since the GUI last read it (clip LED, googly eyes).
    peak: Arc<AtomicF32>,
}

impl Default for SosigMaxxer {
    fn default() -> Self {
        Self {
            params: Arc::new(SosigParams::default()),
            dsp: dsp::Fattener::new(48000.0),
            peak: Arc::new(AtomicF32::new(0.0)),
        }
    }
}

impl Plugin for SosigMaxxer {
    const NAME: &'static str = "Sosig Maxxer";
    const VENDOR: &'static str = "agenttux";
    const URL: &'static str = env!("CARGO_PKG_REPOSITORY");
    const EMAIL: &'static str = "";
    const VERSION: &'static str = env!("CARGO_PKG_VERSION");

    const AUDIO_IO_LAYOUTS: &'static [AudioIOLayout] = &[
        AudioIOLayout {
            main_input_channels: NonZeroU32::new(2),
            main_output_channels: NonZeroU32::new(2),
            ..AudioIOLayout::const_default()
        },
        AudioIOLayout {
            main_input_channels: NonZeroU32::new(1),
            main_output_channels: NonZeroU32::new(1),
            ..AudioIOLayout::const_default()
        },
    ];
    const SAMPLE_ACCURATE_AUTOMATION: bool = false;
    type SysExMessage = ();
    type BackgroundTask = ();

    fn params(&self) -> Arc<dyn Params> {
        self.params.clone()
    }

    fn editor(&mut self, _: AsyncExecutor<Self>) -> Option<Box<dyn Editor>> {
        editor::create(self.params.clone(), self.peak.clone())
    }

    fn initialize(
        &mut self,
        _: &AudioIOLayout,
        cfg: &BufferConfig,
        _: &mut impl InitContext<Self>,
    ) -> bool {
        self.dsp.reset(cfg.sample_rate);
        true
    }

    fn reset(&mut self) {
        let sr = self.dsp.sample_rate();
        self.dsp.reset(sr);
    }

    fn process(
        &mut self,
        buffer: &mut Buffer,
        _: &mut AuxiliaryBuffers,
        _: &mut impl ProcessContext<Self>,
    ) -> ProcessStatus {
        let (fat, color, gain) = (
            self.params.fat.value(),
            self.params.color.value(),
            self.params.gain.value(),
        );
        let mut peak = 0f32;
        for mut frame in buffer.iter_samples() {
            let mut it = frame.iter_mut();
            match (it.next(), it.next()) {
                (Some(l), Some(r)) => {
                    (*l, *r) = self.dsp.process_frame(*l, *r, fat, color, gain);
                    peak = peak.max(l.abs()).max(r.abs());
                }
                (Some(m), None) => {
                    *m = self.dsp.process_frame(*m, *m, fat, color, gain).0;
                    peak = peak.max(m.abs());
                }
                _ => {}
            }
        }
        self.peak
            .fetch_max(peak, std::sync::atomic::Ordering::Relaxed);
        ProcessStatus::Normal
    }
}

impl ClapPlugin for SosigMaxxer {
    const CLAP_ID: &'static str = "org.popat.sosig-maxxer";
    const CLAP_DESCRIPTION: Option<&'static str> = Some(env!("CARGO_PKG_DESCRIPTION"));
    const CLAP_MANUAL_URL: Option<&'static str> = None;
    const CLAP_SUPPORT_URL: Option<&'static str> = None;
    const CLAP_FEATURES: &'static [ClapFeature] = &[
        ClapFeature::AudioEffect,
        ClapFeature::Distortion,
        ClapFeature::Stereo,
        ClapFeature::Mono,
    ];
}

impl Vst3Plugin for SosigMaxxer {
    const VST3_CLASS_ID: [u8; 16] = *b"SosigMaxxerFatnr";
    const VST3_SUBCATEGORIES: &'static [Vst3SubCategory] =
        &[Vst3SubCategory::Fx, Vst3SubCategory::Distortion];
}

nih_export_clap!(SosigMaxxer);
nih_export_vst3!(SosigMaxxer);
