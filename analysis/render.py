"""Load a plugin headlessly (pedalboard) and render audio through it.

The reference plugin only loads as an Audio Unit (its VST3 aborts when scanned headless),
so AU bundles must sit in ~/Library/Audio/Plug-Ins/Components/.
"""
import os

import numpy as np
import pedalboard

# Our canonical knob names -> prefixes matched against each plugin's parameter keys.
KNOBS = ("fat", "color", "gain")


def load(path):
    path = os.path.expanduser(path)
    if path.endswith(".component"):
        names = pedalboard.AudioUnitPlugin.get_plugin_names_for_file(path)
        return pedalboard.AudioUnitPlugin(path, plugin_name=names[0])
    return pedalboard.load_plugin(path)


def _knob_keys(plugin):
    keys = list(plugin.parameters.keys())
    out = {}
    for knob in KNOBS:
        match = [k for k in keys if k.startswith(knob) or (knob == "fat" and k.startswith("maxx"))]
        if len(match) != 1:
            raise KeyError(f"param for {knob!r} not unique in {keys}")
        out[knob] = match[0]
    return out


def set_params(plugin, fat, color, gain):
    keys = _knob_keys(plugin)
    for knob, val in zip(KNOBS, (fat, color, gain)):
        plugin.parameters[keys[knob]].raw_value = float(val)


def render(plugin, audio, sr, fat, color, gain, tail_s=1.0, buffer_size=512):
    audio = np.asarray(audio, dtype=np.float32)
    tail = np.zeros((audio.shape[0], int(tail_s * sr)), dtype=np.float32)
    plugin.reset()
    set_params(plugin, fat, color, gain)
    return plugin(np.concatenate([audio, tail], axis=1), sr, buffer_size=buffer_size, reset=True)


def render_automated(plugin, audio, sr, schedule, buffer_size=64):
    """schedule: list of (start_sample, fat, color, gain), sorted, first at 0.
    Params change between chunks; plugin state carries over (reset=False)."""
    audio = np.asarray(audio, dtype=np.float32)
    plugin.reset()
    bounds = [s[0] for s in schedule] + [audio.shape[1]]
    out = []
    for (start, fat, color, gain), end in zip(schedule, bounds[1:]):
        set_params(plugin, fat, color, gain)
        out.append(plugin(audio[:, start:end], sr, buffer_size=buffer_size, reset=False))
    return np.concatenate(out, axis=1)
