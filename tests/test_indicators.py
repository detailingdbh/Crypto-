import pytest

from bot.indicators import atr, ema, rsi


def test_ema_constant_series_equals_value():
    out = ema([5.0] * 10, 3)
    assert out[:2] == [None, None]
    assert all(v == pytest.approx(5.0) for v in out[2:])


def test_ema_known_values():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_too_short():
    assert ema([1, 2], 3) == [None, None]


def test_rsi_bounds():
    assert rsi(list(range(1, 30)), 14)[-1] == 100.0
    assert rsi(list(range(30, 1, -1)), 14)[-1] == pytest.approx(0.0)
    assert rsi([10.0] * 30, 14)[-1] == 50.0


def test_rsi_in_range_on_mixed_series():
    values = [10, 11, 10.5, 12, 11, 13, 12.5, 14, 13, 12, 13, 14, 15, 14, 16, 15]
    r = rsi(values, 14)[-1]
    assert 0 < r < 100


def test_atr_constant_range():
    n = 20
    highs, lows, closes = [11.0] * n, [9.0] * n, [10.0] * n
    out = atr(highs, lows, closes, 5)
    assert out[4] is None
    assert out[-1] == pytest.approx(2.0)
