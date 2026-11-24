//! Monochrome GUI: sausage icon (assets/sausage.svg) with a procedural face that goes from a wide
//! smile (Fat 0) to gritted teeth (Fat 1); googly pupils get kicked around by output level.
//! Two big knobs (Maxx, Color), a small Gain knob between them with the clip LED beside it.

use crate::SosigParams;
use nih_plug::prelude::*;
use nih_plug_egui::egui::{
    self, epaint::CubicBezierShape, pos2, vec2, Align2, Color32, FontId, Pos2, Rect, Sense, Stroke,
    Vec2,
};
use nih_plug_egui::{create_egui_editor, EguiState};
use std::f32::consts::PI;
use std::sync::atomic::Ordering::Relaxed;
use std::sync::Arc;

const BLACK: Color32 = Color32::from_rgb(0x00, 0x00, 0x00);
const WHITE: Color32 = Color32::from_rgb(0xff, 0xff, 0xff);
const DARK: Color32 = Color32::from_rgb(0x22, 0x22, 0x22);
const MID: Color32 = Color32::from_rgb(0x77, 0x77, 0x77);
const LIGHT: Color32 = Color32::from_rgb(0xcc, 0xcc, 0xcc);

pub const SIZE: (u32, u32) = (560, 300);

/// Where the face sits on the icon, as fractions of the icon's square: centre x, centre y, width.
/// Tuned by eye to assets/sausage.svg; retune when the icon changes.
const FACE: (f32, f32, f32) = (0.67, 0.47, 0.25);

/// Face geometry as a pure function of Fat, so it can be tested without a window.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FaceGeom {
    /// Mouth curvature: +1 big smile, 0 flat, -1 grimace.
    pub smile: f32,
    /// 0..1 opacity of the gritted-teeth mouth (0 below Fat 0.6).
    pub teeth: f32,
    /// 0..1 fraction of each eye covered by the upper lid.
    pub lid: f32,
    /// 0..1 strength of the angry brows.
    pub brow: f32,
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

pub fn face_shape(fat: f32) -> FaceGeom {
    let fat = fat.clamp(0.0, 1.0);
    FaceGeom {
        smile: 1.0 - 2.0 * fat,
        teeth: smoothstep(0.6, 0.85, fat),
        lid: 0.45 * fat,
        brow: smoothstep(0.7, 1.0, fat),
    }
}

/// GUI-only animation state.
#[derive(Default)]
struct Anim {
    pupils: [(Vec2, Vec2); 2], // (offset in eye radii, velocity)
    level: f32,
    clip_hold: f32,
    t: f64,
}

pub fn create(params: Arc<SosigParams>, peak: Arc<AtomicF32>) -> Option<Box<dyn Editor>> {
    create_egui_editor(
        params.editor_state.clone(),
        Anim::default(),
        |ctx, _| {
            egui_extras::install_image_loaders(ctx);
            let mut v = egui::Visuals::light();
            v.panel_fill = WHITE;
            v.override_text_color = Some(BLACK);
            ctx.set_visuals(v);
        },
        move |ctx, setter, anim| {
            let now = ctx.input(|i| i.time);
            let dt = ((now - anim.t) as f32).clamp(0.0, 0.05);
            anim.t = now;
            step(anim, peak.swap(0.0, Relaxed), dt);
            ctx.request_repaint();

            egui::CentralPanel::default()
                .frame(egui::Frame::NONE.fill(WHITE))
                .show(ctx, |ui| {
                    let r = ui.max_rect();
                    // scale the fixed 560x300 layout to whatever the window is
                    let s = (r.width() / SIZE.0 as f32).min(r.height() / SIZE.1 as f32);
                    let at = |x: f32, y: f32| r.min + vec2(x, y) * s;

                    let icon = Rect::from_min_size(at(10.0, 10.0), Vec2::splat(260.0 * s));
                    egui::Image::new(egui::include_image!("../assets/sausage.svg"))
                        .tint(BLACK)
                        .paint_at(ui, icon);
                    let fc = icon.min + vec2(FACE.0, FACE.1) * icon.width();
                    draw_face(
                        ui.painter(),
                        fc,
                        FACE.2 * icon.width(),
                        face_shape(params.fat.value()),
                        anim,
                    );

                    knob(
                        ui,
                        setter,
                        &params.fat,
                        at(340.0, 105.0),
                        58.0 * s,
                        "MAXX",
                        None,
                    );
                    knob(
                        ui,
                        setter,
                        &params.color,
                        at(480.0, 170.0),
                        58.0 * s,
                        "COLOR",
                        None,
                    );
                    // like the original: drag steps 0.5 dB, Shift-drag 0.1 dB
                    let db = |d: f32| d / crate::GAIN_DB;
                    knob(
                        ui,
                        setter,
                        &params.gain,
                        at(395.0, 235.0),
                        20.0 * s,
                        "GAIN",
                        Some((db(0.5), db(0.1))),
                    );

                    // clip LED, left of the Gain knob
                    ui.painter().circle(
                        at(357.0, 235.0),
                        6.0 * s,
                        if anim.clip_hold > 0.0 { BLACK } else { WHITE },
                        Stroke::new(2.0f32, BLACK),
                    );
                    ui.painter().text(
                        at(14.0, 290.0),
                        Align2::LEFT_BOTTOM,
                        "SOSIG MAXXER",
                        FontId::proportional(20.0 * s),
                        BLACK,
                    );
                    // CC BY 3.0 credit for assets/sausage.svg, on the version line clear of the knobs
                    ui.painter().text(
                        at(546.0, 290.0),
                        Align2::RIGHT_BOTTOM,
                        concat!(
                            "Sausage icon by endang firmansyah, Noun Project (CC BY 3.0)   v",
                            env!("CARGO_PKG_VERSION")
                        ),
                        FontId::proportional(9.0 * s),
                        MID,
                    );
                });
        },
    )
}

/// Rotary knob: vertical drag (Shift = fine), double-click resets. 270 degree sweep.
/// `step`: optional (normal, Shift) snap sizes in normalized units, counted from 0.
fn knob(
    ui: &mut egui::Ui,
    setter: &ParamSetter,
    p: &FloatParam,
    c: Pos2,
    r: f32,
    label: &str,
    step: Option<(f32, f32)>,
) {
    let id = ui.id().with(label);
    let resp = ui.interact(
        Rect::from_center_size(c, Vec2::splat(r * 2.2)),
        id,
        Sense::click_and_drag(),
    );
    if resp.double_clicked() {
        setter.begin_set_parameter(p);
        setter.set_parameter(p, p.default_plain_value());
        setter.end_set_parameter(p);
    } else if resp.drag_started() {
        setter.begin_set_parameter(p);
        // unsnapped drag position, so small moves add up instead of rounding away
        ui.data_mut(|d| d.insert_temp(id, p.unmodulated_normalized_value()));
    }
    if resp.dragged() {
        let fine = ui.input(|i| i.modifiers.shift);
        let dy = resp.drag_delta().y / if fine { 1000.0 } else { 200.0 };
        let raw = ui.data_mut(|d| {
            let r = d.get_temp_mut_or(id, p.unmodulated_normalized_value());
            *r = (*r - dy).clamp(0.0, 1.0);
            *r
        });
        let v = match step {
            Some((n, f)) => {
                let s = if fine { f } else { n };
                ((raw / s).round() * s).clamp(0.0, 1.0)
            }
            None => raw,
        };
        setter.set_parameter_normalized(p, v);
    }
    if resp.drag_stopped() {
        setter.end_set_parameter(p);
    }

    let v = p.unmodulated_normalized_value();
    let dir = |t: f32| {
        let a = (-135.0 + 270.0 * t) * PI / 180.0;
        vec2(a.sin(), -a.cos())
    };
    let pt = ui.painter();
    let w = (r * 0.12).max(2.0);
    // value arc
    let arc = |from: f32, to: f32, col: Color32| {
        let n = 48;
        let pts: Vec<Pos2> = (0..=n)
            .map(|i| c + dir(from + (to - from) * i as f32 / n as f32) * (r + w * 1.6))
            .collect();
        pt.add(egui::Shape::line(pts, Stroke::new(w, col)));
    };
    arc(0.0, 1.0, LIGHT);
    arc(0.0, v, DARK);
    pt.circle(
        c,
        r,
        if resp.hovered() || resp.dragged() {
            LIGHT
        } else {
            WHITE
        },
        Stroke::new(w * 0.8, BLACK),
    );
    pt.line_segment(
        [c + dir(v) * r * 0.25, c + dir(v) * r * 0.85],
        Stroke::new(w, BLACK),
    );

    let text = if resp.hovered() || resp.dragged() {
        p.to_string()
    } else {
        label.to_owned()
    };
    let size = if r > 30.0 { 16.0 } else { 12.0 };
    pt.text(
        c + vec2(0.0, r + w * 2.0 + 6.0),
        Align2::CENTER_TOP,
        text,
        FontId::proportional(size),
        BLACK,
    );
}

/// Advance pupils (gravity + kicks from level jumps, bouncing inside the eye) and the clip hold.
fn step(a: &mut Anim, peak: f32, dt: f32) {
    let kick = (peak - a.level).max(0.0);
    a.level = peak.max(a.level * (-dt / 0.08).exp());
    a.clip_hold = if peak >= crate::dsp::CEIL as f32 * 0.999 {
        0.25
    } else {
        (a.clip_hold - dt).max(0.0)
    };
    for (i, (pos, vel)) in a.pupils.iter_mut().enumerate() {
        let side = if i == 0 { -1.0 } else { 1.0 };
        *vel += vec2(side * kick * 6.0, -kick * 14.0) + vec2(0.0, 9.0) * dt; // gravity pulls down
        *vel *= (-dt * 2.5).exp();
        *pos += *vel * dt;
        let max = 0.45; // pupil centre limit, in eye radii
        if pos.length() > max {
            let n = pos.normalized();
            *pos = n * max;
            *vel -= 1.6 * vel.dot(n) * n; // bounce, loses a bit
        }
    }
}

/// Face centred at `c`, `w` wide.
fn draw_face(p: &egui::Painter, c: Pos2, w: f32, g: FaceGeom, a: &Anim) {
    let er = w * 0.2;
    let ink = (w * 0.035).max(2.0);
    for (i, s) in [-1.0f32, 1.0].into_iter().enumerate() {
        let e = pos2(c.x + s * w * 0.24, c.y - w * 0.12);
        p.circle(e, er, WHITE, Stroke::new(ink, BLACK));
        p.circle_filled(e + a.pupils[i].0 * er, er * 0.45, BLACK);
        if g.lid > 0.0 {
            let lid = Rect::from_min_max(
                e - Vec2::splat(er + ink),
                pos2(e.x + er + ink, e.y - er + 2.0 * er * g.lid),
            );
            p.with_clip_rect(lid)
                .circle(e, er, MID, Stroke::new(ink, BLACK));
            p.line_segment(
                [pos2(e.x - er, lid.max.y), pos2(e.x + er, lid.max.y)],
                Stroke::new(ink, BLACK),
            );
        }
        if g.brow > 0.0 {
            // angry: inner ends (toward the nose) low, outer ends high
            let y = e.y - er * 1.4;
            let tilt = er * 0.5 * g.brow;
            p.line_segment(
                [
                    pos2(e.x - s * er * 0.9, y + tilt),
                    pos2(e.x + s * er * 0.9, y - tilt),
                ],
                Stroke::new(ink * 1.3 * g.brow, BLACK),
            );
        }
    }

    // mouth: bezier smile -> grimace, gritted teeth fade in on top
    let m = pos2(c.x, c.y + w * 0.25);
    let mw = w * 0.3;
    let bend = g.smile * w * 0.16;
    let curve = [
        pos2(m.x - mw, m.y),
        pos2(m.x - mw * 0.5, m.y + bend),
        pos2(m.x + mw * 0.5, m.y + bend),
        pos2(m.x + mw, m.y),
    ];
    if g.teeth < 1.0 {
        let col = BLACK.gamma_multiply(1.0 - g.teeth);
        p.add(CubicBezierShape::from_points_stroke(
            curve,
            false,
            Color32::TRANSPARENT,
            Stroke::new(ink, col),
        ));
    }
    if g.teeth > 0.0 {
        let r = Rect::from_center_size(m, vec2(mw * 2.1, w * 0.2));
        let s = Stroke::new(ink * 0.8, BLACK.gamma_multiply(g.teeth));
        p.rect(
            r,
            w * 0.04,
            WHITE.gamma_multiply(g.teeth),
            s,
            egui::StrokeKind::Middle,
        );
        p.line_segment([r.left_center(), r.right_center()], s);
        for k in 1..6 {
            let x = r.min.x + r.width() * k as f32 / 6.0;
            p.line_segment([pos2(x, r.min.y), pos2(x, r.max.y)], s);
        }
    }
}

pub fn default_state() -> Arc<EguiState> {
    EguiState::from_size(SIZE.0, SIZE.1)
}
