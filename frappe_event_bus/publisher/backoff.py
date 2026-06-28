"""Pure exponential backoff calculation for outbox retries."""

from __future__ import annotations

# A sane default ceiling so retries never schedule absurdly far out.
DEFAULT_MAX_BACKOFF_SECONDS = 24 * 60 * 60


def compute_backoff_seconds(
	attempt: int,
	base_seconds: int,
	max_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
) -> int:
	"""Return exponential backoff delay in seconds for a given attempt.

	Delay = ``base_seconds * 2 ** (attempt - 1)``, clamped to ``max_seconds``.
	Attempt numbers below 1 are treated as the first attempt.

	Args:
		attempt: 1-based attempt number that just failed.
		base_seconds: Base backoff interval.
		max_seconds: Upper bound on the returned delay.

	Returns:
		Non-negative delay in seconds.
	"""
	normalized_attempt = max(attempt, 1)
	if base_seconds <= 0:
		return 0
	delay = base_seconds * (2 ** (normalized_attempt - 1))
	return min(delay, max_seconds)
