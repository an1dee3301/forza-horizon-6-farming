from fh6.wheelspin_catalog import PROTECTED_CARS, PRIORITY_TARGETS, identify_protected


def test_catalog_contains_exactly_45_exclusive_cars_without_retention_policy():
    assert len(PROTECTED_CARS) == 45
    assert len({car.identity for car in PROTECTED_CARS}) == 45
    assert all(car.wheelspin_exclusive and car.official_route == "Wheelspin, Seasonal" for car in PROTECTED_CARS)


def test_priority_targets_are_part_of_the_full_catalog():
    identities = {car.identity for car in PROTECTED_CARS}
    assert len(PRIORITY_TARGETS) == 7
    assert set(PRIORITY_TARGETS) <= identities


def protected(text):
    match = identify_protected(text)
    return match.car.display_name if match else None


def test_requested_exact_and_alias_matches():
    assert protected("2015 KOENIGSEGG ONE:1") == "2015 Koenigsegg One:1"
    assert protected("2011 LAMBORGHINI SESTO ELEMENTO") == "2011 Lamborghini Sesto Elemento"
    assert protected("2021 RIMAC NEVERA") == "2021 Rimac Nevera"
    assert protected("1998 MERCEDES-BENZ AMG CLK GTR") == "1998 Mercedes-Benz AMG CLK GTR"
    assert protected("1998 MERCEDES BENZ CLK GTR") == "1998 Mercedes-Benz AMG CLK GTR"
    assert protected("2019 APOLLO INTENSA EMOZIONE") == "2019 Apollo Intensa Emozione"
    assert protected("2012 FERRARI 599XX EVOLUTION") == "2012 Ferrari 599XX Evolution"


def test_similar_cars_are_not_protected():
    assert protected("1984 AUDI SPORT QUATTRO") == "1984 Audi Sport quattro"
    assert protected("1986 AUDI #2 AUDI SPORT QUATTRO S1") is None
    assert protected("1995 PORSCHE 911 GT2") == "1995 Porsche 911 GT2"
    assert protected("2018 PORSCHE 911 GT2 RS") is None
    assert protected("2016 LAMBORGHINI CENTENARIO LP 770-4") is None


def test_partial_or_ambiguous_text_fails_closed():
    assert identify_protected("SESTO ELEMENTO") is None
    assert identify_protected("2011 LAMBORGHINI") is None
    assert identify_protected("911 GT2") is None
