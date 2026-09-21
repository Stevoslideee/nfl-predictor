from odds import american_to_prob, blended_probability


def test_blended_probability_simple_average():
    assert blended_probability(0.6, 0.8) == 0.7


def test_blended_probability_agreement_stays_put():
    assert blended_probability(0.5, 0.5) == 0.5


def test_american_to_prob_favorite():
    # a -200 favorite implies roughly a 2/3 win probability
    assert abs(american_to_prob(-200) - (2 / 3)) < 1e-9


def test_american_to_prob_underdog():
    assert abs(american_to_prob(150) - 0.4) < 1e-9
