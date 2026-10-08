"""Pure, versioned evaluator for locally recorded experiment measurements."""
from __future__ import annotations

EVALUATION_VERSION = "v1"


def evaluate(forecast: dict, measurements: list[tuple[str, float]]) -> dict:
    """Compare a metric sum with its forecast without I/O or randomness.

    ``forecast`` accepts ``metric`` and either ``expected_value`` or ``value``.
    Missing values are deliberately treated as zero, making incomplete local
    plans reproducible rather than silently consulting an external service.
    """
    metric = str(forecast.get("metric", "primary"))
    expected = float(forecast.get("expected_value", forecast.get("value", 0)))
    actual = sum(value for name, value in measurements if name == metric)
    delta = actual - expected
    ratio = None if expected == 0 else actual / expected
    return {
        "evaluation_version": EVALUATION_VERSION,
        "metric": metric,
        "forecast_value": expected,
        "actual_value": actual,
        "delta": delta,
        "ratio": ratio,
        "outcome": "met" if actual >= expected else "below_forecast",
        "measurement_count": sum(1 for name, _ in measurements if name == metric),
    }
