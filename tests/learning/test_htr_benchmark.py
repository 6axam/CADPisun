from __future__ import annotations

import pytest

from handwriting_plotter.learning.htr_benchmark import HtrBenchmarkSample, HtrPrediction, summarize_htr_benchmark


def test_summary_uses_nfc_cer_wer_and_reports_resources() -> None:
    samples = (HtrBenchmarkSample("a", "0" * 64, "їжа тут", "real", "private_user_material"),)
    predictions = (HtrPrediction("a", "crnn", "pin", "їжа там", 12.5, 1234),)
    summary = summarize_htr_benchmark(samples, predictions)
    assert summary.cer > 0 and summary.wer == pytest.approx(0.5)
    assert summary.mean_elapsed_ms == 12.5 and summary.peak_rss_bytes == 1234


def test_synthetic_samples_cannot_claim_an_htr_benchmark() -> None:
    samples = (HtrBenchmarkSample("a", "0" * 64, "мама", "synthetic", "authorized"),)
    predictions = (HtrPrediction("a", "crnn", "pin", "мама", 1.0, None),)
    with pytest.raises(ValueError, match="HTR_BENCHMARK_REQUIRES_REAL_SAMPLES"):
        summarize_htr_benchmark(samples, predictions)
