import sys
import unittest
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from hotel_quality_gate import (  # noqa: E402
    MAX_PAYLOAD_BYTES,
    VectorQualityGateFailure,
    check_vector_quality_gate,
)


def _passing_metrics(**overrides):
    metrics = {
        "total": 100,
        "empty_embedding_text": 0,
        "max_payload_bytes": 1000,
        "missing_coordinates": 0,
    }
    metrics.update(overrides)
    return metrics


class VectorQualityGateTests(unittest.TestCase):
    def test_passing_metrics_do_not_raise(self):
        check_vector_quality_gate(_passing_metrics())  # must not raise

    def test_empty_metrics_raises(self):
        with self.assertRaises(VectorQualityGateFailure):
            check_vector_quality_gate({})

    def test_none_like_metrics_raises(self):
        with self.assertRaises(VectorQualityGateFailure):
            check_vector_quality_gate(None or {})

    def test_missing_total_key_raises(self):
        metrics = _passing_metrics()
        del metrics["total"]
        with self.assertRaises(VectorQualityGateFailure):
            check_vector_quality_gate(metrics)

    def test_total_zero_raises(self):
        with self.assertRaises(VectorQualityGateFailure):
            check_vector_quality_gate(_passing_metrics(total=0))

    def test_empty_embedding_text_breach_raises(self):
        # 6/100 = 6% > 5% threshold
        with self.assertRaises(VectorQualityGateFailure) as ctx:
            check_vector_quality_gate(_passing_metrics(empty_embedding_text=6))
        self.assertIn("empty_embedding_text", str(ctx.exception))

    def test_empty_embedding_text_at_threshold_does_not_raise(self):
        # 5/100 = 5%, not > 5%
        check_vector_quality_gate(_passing_metrics(empty_embedding_text=5))

    def test_max_payload_bytes_breach_raises(self):
        with self.assertRaises(VectorQualityGateFailure) as ctx:
            check_vector_quality_gate(_passing_metrics(max_payload_bytes=MAX_PAYLOAD_BYTES + 1))
        self.assertIn("max_payload_bytes", str(ctx.exception))

    def test_missing_coordinates_breach_warns_but_does_not_raise(self):
        # 51/100 = 51% > 50% threshold, but this metric only warns.
        check_vector_quality_gate(_passing_metrics(missing_coordinates=51))


if __name__ == "__main__":
    unittest.main()
