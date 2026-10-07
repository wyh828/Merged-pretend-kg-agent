import pandas as pd
from techtrend.prediction.signal import concept_share_momentum
from techtrend.prediction.kleinberg import detect_top_bursts


def test_future_only_entities_cannot_change_historical_normalization():
    history = pd.DataFrame([[1, 2, 3, 6], [3, 4, 4, 4]], index=["a", "b"])
    scores = concept_share_momentum(history)
    augmented = history.copy()
    for i in range(20): augmented.loc[f"future_{i}"] = [0, 0, 0, 0]
    assert concept_share_momentum(augmented) == scores
    assert set(detect_top_bursts(augmented, 10)["concept"]) == {"a", "b"}
