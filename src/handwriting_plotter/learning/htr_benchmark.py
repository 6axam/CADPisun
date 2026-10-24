"""Provider-neutral, reproducible HTR benchmark accounting."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from handwriting_plotter.domain.models import canonical_json_bytes, strict_json_loads


@dataclass(frozen=True, slots=True)
class HtrBenchmarkSample:
    sample_id: str
    crop_sha256: str
    transcript: str
    source_kind: Literal["real", "synthetic"]
    rights_status: Literal["private_user_material", "authorized"]
    partition: Literal["tuning", "control"] = "tuning"


@dataclass(frozen=True, slots=True)
class HtrBenchmarkSplit:
    """Explicit text-level split; callers must not select on ``control``."""

    tuning: tuple[HtrBenchmarkSample, ...]
    control: tuple[HtrBenchmarkSample, ...]


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


def serialize_benchmark_summary(summary: HtrBenchmarkSummary) -> bytes:
    """Return a canonical, checksummed report fragment safe for later comparison."""

    payload = {
        "format": "hp-htr-benchmark-summary",
        "schema_version": "1.0",
        "provider_id": summary.provider_id,
        "model_revision": summary.model_revision,
        "sample_count": summary.sample_count,
        "cer": summary.cer,
        "wer": summary.wer,
        "mean_elapsed_ms": summary.mean_elapsed_ms,
        "peak_rss_bytes": summary.peak_rss_bytes,
    }
    return canonical_json_bytes({"payload": payload, "sha256": sha256(canonical_json_bytes(payload)).hexdigest()})


def load_benchmark_summary(data: bytes) -> HtrBenchmarkSummary:
    """Verify and load a canonical report fragment without executing providers."""

    decoded = strict_json_loads(data)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("payload"), dict):
        raise ValueError("INVALID_HTR_BENCHMARK_REPORT")
    payload = decoded["payload"]
    if decoded.get("sha256") != sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("HTR_BENCHMARK_REPORT_HASH_MISMATCH")
    if payload.get("format") != "hp-htr-benchmark-summary" or payload.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_HTR_BENCHMARK_REPORT")
    return HtrBenchmarkSummary(
        provider_id=str(payload["provider_id"]), model_revision=str(payload["model_revision"]),
        sample_count=int(payload["sample_count"]), cer=float(payload["cer"]), wer=float(payload["wer"]),
        mean_elapsed_ms=float(payload["mean_elapsed_ms"]),
        peak_rss_bytes=None if payload["peak_rss_bytes"] is None else int(payload["peak_rss_bytes"]),
    )


def split_htr_benchmark_samples(samples: tuple[HtrBenchmarkSample, ...]) -> HtrBenchmarkSplit:
    """Separate real benchmark rows before provider selection or final scoring."""

    if not samples:
        raise ValueError("HTR_BENCHMARK_REQUIRES_SAMPLES")
    identifiers = [item.sample_id for item in samples]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("HTR_BENCHMARK_DUPLICATE_SAMPLE_ID")
    tuning = tuple(item for item in samples if item.partition == "tuning")
    control = tuple(item for item in samples if item.partition == "control")
    if not tuning or not control:
        raise ValueError("HTR_BENCHMARK_REQUIRES_TUNING_AND_CONTROL")
    return HtrBenchmarkSplit(tuning=tuning, control=control)


def summarize_htr_partition(
    samples: tuple[HtrBenchmarkSample, ...],
    predictions: tuple[HtrPrediction, ...],
    *,
    partition: Literal["tuning", "control"],
) -> HtrBenchmarkSummary:
    """Score exactly one frozen partition and reject accidental cross-partition rows."""

    selected = tuple(item for item in samples if item.partition == partition)
    if not selected:
        raise ValueError("HTR_BENCHMARK_EMPTY_PARTITION")
    if any(item.sample_id not in {sample.sample_id for sample in selected} for item in predictions):
        raise ValueError("HTR_BENCHMARK_CROSS_PARTITION_PREDICTION")
    return summarize_htr_benchmark(selected, predictions)


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
