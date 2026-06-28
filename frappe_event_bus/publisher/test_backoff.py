"""Unit tests for retry backoff calculation."""

import unittest

from frappe_event_bus.publisher.backoff import compute_backoff_seconds


class TestComputeBackoff(unittest.TestCase):
	def test_first_attempt(self) -> None:
		# attempt 1 -> base * 2^0 = base
		self.assertEqual(compute_backoff_seconds(attempt=1, base_seconds=60), 60)

	def test_exponential_growth(self) -> None:
		self.assertEqual(compute_backoff_seconds(attempt=2, base_seconds=60), 120)
		self.assertEqual(compute_backoff_seconds(attempt=3, base_seconds=60), 240)

	def test_zero_or_negative_attempt_treated_as_first(self) -> None:
		self.assertEqual(compute_backoff_seconds(attempt=0, base_seconds=30), 30)
		self.assertEqual(compute_backoff_seconds(attempt=-5, base_seconds=30), 30)

	def test_capped(self) -> None:
		self.assertEqual(
			compute_backoff_seconds(attempt=20, base_seconds=60, max_seconds=3600), 3600
		)

	def test_base_zero(self) -> None:
		self.assertEqual(compute_backoff_seconds(attempt=5, base_seconds=0), 0)


if __name__ == "__main__":
	unittest.main()
