"""Provider-neutral, reproducible HTR benchmark accounting."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class HtrBenchmarkSample:
    sample_id: str
    crop_sha256: str
    transcript: str
    source_kind: Literal["real", "synthetic"]
    rights_status: Literal["private_user_material", "authorized"]


@dataclass(frozen=True, slots=True)
class HtrPrediction:
    sample_id: str
    provider_id: str
    model_revision: str
    prediction: str
    elapsed_ms: float
    peak_rss_bytes: int | None


@dataclass(frozen=True, slots=True)
class HtrBenchmarkSummary:
    provider_id: str
    model_revision: str
    sample_count: int
    cer: float
    wer: float
    mean_elapsed_ms: float
    peak_rss_bytes: int | None


def summarize_htr_benchmark(
    samples: tuple[HtrBenchmarkSample, ...], predictions: tuple[HtrPrediction, ...]
) -> HtrBenchmarkSummary:
    """Calculate NFC CER/WER for exactly one model over real authorised lines."""

    if not samples or not any(sample.source_kind == "real" for sample in samples):
        raise ValueError("HTR_BENCHMARK_REQUIRES_REAL_SAMPLES")
    sample_by_id = {sample.sample_id: sample for sample in samples}
    if len(sample_by_id) != len(samples) or {item.sample_id for item in predictions} != set(sample_by_id):
        raise ValueError("HTR_BENCHMARK_SAMPLE_SET_MISMATCH")
    provider_ids = {item.provider_id for item in predictions}
    revisions = {item.model_revision for item in predictions}
    if len(provider_ids) != 1 or len(revisions) != 1:
        raise ValueError("HTR_BENCHMARK_REQUIRES_ONE_MODEL")
    if any(item.elapsed_ms < 0 for item in predictions):
        raise ValueError("HTR_BENCHMARK_INVALID_TIMING")
    character_errors = total_characters = word_errors = total_words = 0
    for item in predictions:
        expected = _nfc(sample_by_id[item.sample_id].transcript)
        actual = _nfc(item.prediction)
        character_errors += _distance(tuple(expected), tuple(actual))
        total_characters += max(1, len(expected))
        expected_words, actual_words = tuple(expected.split()), tuple(actual.split())
        word_errors += _distance(expected_words, actual_words)
        total_words += max(1, len(expected_words))
    memory = [item.peak_rss_bytes for item in predictions if item.peak_rss_bytes is not None]
    return HtrBenchmarkSummary(
        provider_id=next(iter(provider_ids)), model_revision=next(iter(revisions)),
        sample_count=len(samples), cer=character_errors / total_characters,
        wer=word_errors / total_words,
        mean_elapsed_ms=sum(item.elapsed_ms for item in predictions) / len(predictions),
        peak_rss_bytes=max(memory) if memory else None,
    )


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _distance(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    row = list(range(len(right) + 1))
    for index, value in enumerate(left, start=1):
        next_row = [index]
        for column, other in enumerate(right, start=1):
            next_row.append(min(next_row[-1] + 1, row[column] + 1, row[column - 1] + (value != other)))
        row = next_row
    return row[-1]
