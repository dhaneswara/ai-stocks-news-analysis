from app.evaluation.scoring import grade_for, is_hit, is_overconfident, score_call

BAND = 2.0   # hold_band_pct
SCALE = 5.0  # score_scale_pct


def test_is_hit_directional():
    assert is_hit("buy", 3.0, BAND) is True
    assert is_hit("buy", -3.0, BAND) is False
    assert is_hit("sell", -3.0, BAND) is True
    assert is_hit("sell", 3.0, BAND) is False


def test_is_hit_hold_band():
    assert is_hit("hold", 1.0, BAND) is True
    assert is_hit("hold", 2.0, BAND) is True     # edge counts as a hit
    assert is_hit("hold", 3.0, BAND) is False


def test_score_directional_maps_neutral_full_and_zero():
    assert score_call("buy", 0.0, BAND, SCALE) == 50.0
    assert score_call("buy", 5.0, BAND, SCALE) == 100.0    # correct move of one scale -> 100
    assert score_call("buy", -5.0, BAND, SCALE) == 0.0     # wrong move of one scale -> 0
    assert score_call("sell", -5.0, BAND, SCALE) == 100.0
    assert score_call("buy", 50.0, BAND, SCALE) == 100.0   # clamped


def test_score_hold_rewards_flat():
    assert score_call("hold", 0.0, BAND, SCALE) == 100.0
    assert score_call("hold", 2.0, BAND, SCALE) == 50.0    # at the band edge
    assert score_call("hold", 4.0, BAND, SCALE) == 0.0


def test_grade_thresholds():
    assert grade_for(75.0) == "Strong"
    assert grade_for(60.0) == "Strong"
    assert grade_for(50.0) == "Mixed"
    assert grade_for(40.0) == "Weak"
    assert grade_for(10.0) == "Weak"


def test_overconfident_flag():
    # misses are on average MORE confident than hits -> overconfident
    assert is_overconfident([0.5], [0.9]) is True
    assert is_overconfident([0.9], [0.5]) is False
    assert is_overconfident([], [0.9]) is False   # needs at least one of each
    assert is_overconfident([0.5], []) is False
