from collections.abc import Iterator

import numpy as np
import pytest

from pdf_reader.audio.player import AudioChunk, AudioPlayer
from tests.fakes import SAMPLE_RATE, FakeStream, Recorder, StreamFactory, wait_until


def chunk(index: int, length: int, value: float, epoch: int = 1) -> AudioChunk:
    return AudioChunk(index, epoch, np.full(length, value, dtype=np.float32))


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def factory() -> StreamFactory:
    return StreamFactory()


@pytest.fixture
def player(recorder: Recorder, factory: StreamFactory) -> Iterator[AudioPlayer]:
    p = AudioPlayer(SAMPLE_RATE, recorder, stream_factory=factory)
    yield p
    p.close()


def started(recorder: Recorder) -> list[int]:
    return [c.index for c in recorder.named("on_chunk_started")]


def finished(recorder: Recorder) -> list[int]:
    return [c.index for c in recorder.named("on_chunk_finished")]


def test_chunks_play_back_to_back_without_gaps(
    player: AudioPlayer, factory: StreamFactory, recorder: Recorder
) -> None:
    player.offer(chunk(0, 7, 0.1))
    player.offer(chunk(1, 5, 0.2))
    stream = factory.wait_active()

    out = np.concatenate([stream.pump(4), stream.pump(4), stream.pump(4), stream.pump(4)])

    expected = np.array([0.1] * 7 + [0.2] * 5 + [0.0] * 4, dtype=np.float32)
    np.testing.assert_array_equal(out, expected)
    assert wait_until(lambda: finished(recorder) == [0, 1])
    assert started(recorder) == [0, 1]


def test_silence_when_nothing_queued(player: AudioPlayer, factory: StreamFactory) -> None:
    player.resume()
    stream = factory.wait_active()
    np.testing.assert_array_equal(stream.pump(8), np.zeros(8, dtype=np.float32))


def test_pause_keeps_position(player: AudioPlayer, factory: StreamFactory) -> None:
    player.offer(AudioChunk(0, 1, np.arange(1, 11, dtype=np.float32)))
    stream = factory.wait_active()
    np.testing.assert_array_equal(stream.pump(3), [1, 2, 3])

    player.pause()
    assert player.paused
    np.testing.assert_array_equal(stream.pump(3), [0, 0, 0])

    player.resume()
    np.testing.assert_array_equal(stream.pump(3), [4, 5, 6])


def test_clear_stops_immediately(player: AudioPlayer, factory: StreamFactory) -> None:
    player.offer(chunk(0, 10, 0.5))
    player.offer(chunk(1, 10, 0.5))
    stream = factory.wait_active()
    stream.pump(2)
    player.clear()
    assert not player.has_audio
    np.testing.assert_array_equal(stream.pump(4), np.zeros(4, dtype=np.float32))


def test_offer_replaces_queued_chunk_with_same_index(
    player: AudioPlayer, factory: StreamFactory
) -> None:
    player.offer(chunk(0, 2, 0.1))
    player.offer(chunk(1, 2, 0.2))
    assert player.offer(chunk(1, 2, 0.9))  # Regenerated version of sentence 1.
    stream = factory.wait_active()
    np.testing.assert_allclose(stream.pump(4), [0.1, 0.1, 0.9, 0.9])


def test_offer_rejects_sentence_already_playing(
    player: AudioPlayer, factory: StreamFactory
) -> None:
    player.offer(chunk(3, 10, 0.1))
    stream = factory.wait_active()
    stream.pump(2)  # Sentence 3 is now playing.
    assert player.current is not None
    assert not player.offer(chunk(3, 10, 0.9))
    assert not player.offer(chunk(2, 10, 0.9))
    np.testing.assert_allclose(stream.pump(2), [0.1, 0.1])


def test_offer_from_another_epoch_is_queued(player: AudioPlayer, factory: StreamFactory) -> None:
    player.offer(chunk(3, 2, 0.1, epoch=1))
    stream = factory.wait_active()
    stream.pump(1)
    assert player.offer(chunk(3, 2, 0.7, epoch=2))
    np.testing.assert_allclose(stream.pump(3), [0.1, 0.7, 0.7])


def test_empty_chunk_starts_and_finishes(
    player: AudioPlayer, factory: StreamFactory, recorder: Recorder
) -> None:
    player.offer(chunk(0, 0, 0.0))
    player.offer(chunk(1, 2, 0.3))
    stream = factory.wait_active()
    np.testing.assert_allclose(stream.pump(2), [0.3, 0.3])
    assert wait_until(lambda: finished(recorder) == [0, 1])


def test_device_error_is_reported(recorder: Recorder) -> None:
    failing = StreamFactory(fail=OSError("no device"))
    p = AudioPlayer(SAMPLE_RATE, recorder, stream_factory=failing)
    try:
        p.offer(chunk(0, 5, 0.1))
        assert wait_until(lambda: bool(recorder.named("on_audio_error")))
        assert "speaker" in recorder.named("on_audio_error")[0]
    finally:
        p.close()


def test_close_releases_stream(player: AudioPlayer, factory: StreamFactory) -> None:
    player.offer(chunk(0, 5, 0.1))
    stream = factory.wait_active()
    player.close()
    assert stream.closed
    player.offer(chunk(1, 5, 0.1))  # Ignored after close; must not raise or reopen.
    assert factory.stream is stream


def test_idle_stream_is_suspended_and_restarted(recorder: Recorder) -> None:
    factory = StreamFactory()
    p = AudioPlayer(SAMPLE_RATE, recorder, stream_factory=factory)
    try:
        p.resume()
        stream: FakeStream = factory.wait_active()
        stream.pump(SAMPLE_RATE * 6)  # Six seconds of silence.
        assert wait_until(lambda: not stream.active)
        p.offer(chunk(0, 3, 0.4))
        assert wait_until(lambda: stream.active)
    finally:
        p.close()
