from fh6.farm_motion import StationaryWatch, motion_evidence


def test_numeric_zero_overrides_animated_prop_motion():
    watch = StationaryWatch()
    for index in range(5):
        assert not watch.observe(motion_evidence(0, True), 60 + 7 * index, 100 + 7 * index)
    assert watch.observe(motion_evidence(0, True), 95, 135)


def test_visible_motion_is_fallback_only_when_speed_unreadable():
    assert motion_evidence(55, False) == 55
    assert motion_evidence(None, True) == 1
    assert motion_evidence(None, False) == 0
    assert motion_evidence(None, None) is None


def test_prolonged_crawl_also_counts_as_stuck():
    watch = StationaryWatch()
    for index in range(5):
        assert not watch.observe(3, 60 + 7 * index, 100 + 7 * index)
    assert watch.observe(3, 95, 135)
    assert not watch.observe(48, 102, 142)
