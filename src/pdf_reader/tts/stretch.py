"""Speed speech up without changing its pitch (WSOLA time-scale modification).

Waveform-similarity overlap-add cuts the audio into short overlapping frames and
lays them closer together, choosing each frame where it lines up best with the
previous one, so the voice keeps its pitch and sounds smooth rather than choppy.
Used for reading speeds beyond what the voice model can produce by itself.
"""

import numpy as np

from pdf_reader.tts.base import AudioArray

_FRAME_SECONDS = 0.030
_TOLERANCE_SECONDS = 0.010


def time_stretch(audio: AudioArray, factor: float, sample_rate: int) -> AudioArray:
    """Return ``audio`` played ``factor`` times faster, at the same pitch.

    Args:
        audio: Mono float32 samples.
        factor: Speed-up, e.g. 2.0 halves the duration. Values at or below 1 return
            the audio unchanged.
        sample_rate: Samples per second.
    """
    frame = int(_FRAME_SECONDS * sample_rate) // 2 * 2
    if factor <= 1.0 + 1e-3 or audio.size < 2 * frame:
        return audio
    hop_out = frame // 2
    hop_in = hop_out * factor
    tolerance = int(_TOLERANCE_SECONDS * sample_rate)
    # A periodic Hann window at 50% overlap sums to a constant: no amplitude ripple.
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(frame) / frame)).astype(np.float32)

    length = int(audio.size / factor)
    pad = tolerance + frame
    source = np.concatenate(
        [np.zeros(pad, np.float32), audio.astype(np.float32), np.zeros(2 * pad, np.float32)]
    )
    out = np.zeros(length + frame, dtype=np.float32)
    weight = np.zeros(length + frame, dtype=np.float32)

    shift = 0  # How far the chosen frame sits from where it would nominally be.
    k = 0
    while k * hop_out < length:
        start = pad + round(k * hop_in) + shift
        at = k * hop_out
        out[at : at + frame] += source[start : start + frame] * window
        weight[at : at + frame] += window
        # The next frame should continue this one naturally: find the candidate
        # around its nominal position that best matches this frame's continuation.
        follow = source[start + hop_out : start + hop_out + frame]
        nominal = pad + round((k + 1) * hop_in)
        region = source[nominal - tolerance : nominal + tolerance + frame]
        if region.size >= frame + 2 * tolerance and np.any(follow):
            similarity = np.correlate(region, follow, mode="valid")
            shift = int(np.argmax(similarity)) - tolerance
        else:
            shift = 0
        k += 1

    out = out[:length]
    weight = weight[:length]
    np.divide(out, weight, out=out, where=weight > 1e-3)
    return out
