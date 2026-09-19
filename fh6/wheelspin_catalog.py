"""Versioned, offline protected-car catalog for Wheelspin Lab.

Matches are deliberately exact: a year, manufacturer and model alias must all
be present.  Rarity, card colour and the car image never grant protection by
themselves.
"""
from dataclasses import dataclass
import re
import unicodedata


CATALOG_VERSION = "fh6-wheelspin-seasonal-2026-09-18"
SOURCE_DATE = "2026-09-18"
SOURCE_NOTE = "User-approved FH6 Wheelspin, Seasonal snapshot; maintained offline."


def normalize_car_text(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    value = value.upper().replace("&", " AND ")
    return " ".join(re.findall(r"[A-Z0-9]+", value))


# User-owned retention policy. Native duplicate dialogs shorten maker/model
# names (for example Mercedes-Benz AMG CLK GTR becomes M-B CLK-GTR), so every
# destructive action must check these aliases in addition to the catalog.
USER_KEEP_ALIASES = (
    "CLK GTR", "M B CLK GTR", "MB CLK GTR",
    "KOENIGSEGG ONE 1", "ONE 1",
    "HENNESSEY VENOM GT", "VENOM GT",
    "RIMAC NEVERA", "NEVERA",
    "APOLLO INTENSA EMOZIONE", "APOLLO IE", "INTENSA EMOZIONE",
    "FERRARI 599XX EVOLUTION", "599XX EVOLUTION", "599XX EVO",
    "LAMBORGHINI SIAN", "SIAN",
    "FERRARI LAFERRARI", "LAFERRARI",
)

# Native duplicate dialogs often omit the maker. Treat known Lamborghini
# model-only names as protected even when the reward-card OCR loses its header.
LAMBORGHINI_MODEL_ALIASES = (
    "SESTO ELEMENTO", "ESSENZA SCV12", "SCV12", "COUNTACH",
    "HURACAN", "HURACEN", "MURCIELAGO", "CENTENARIO",
    "AVENTADOR", "DIABLO", "GALLARDO", "REVUELTO", "SIAN",
    "VENENO", "REVENTON", "URUS", "MIURA", "JALPA", "ESPADA",
)


def user_keep_match(value):
    text = normalize_car_text(value)
    return any(f" {alias} " in f" {text} " for alias in USER_KEEP_ALIASES)


def lamborghini_candidate(value):
    text = normalize_car_text(value)
    aliases = ("LAMBORGHINI", "LAMBO", *LAMBORGHINI_MODEL_ALIASES)
    return any(f" {alias} " in f" {text} " for alias in aliases)


@dataclass(frozen=True)
class ProtectedCar:
    year: int
    manufacturer: str
    canonical_model: str
    known_display_aliases: tuple = ()
    forza_edition: bool = False
    official_route: str = "Wheelspin, Seasonal"
    protected: bool = True

    @property
    def display_name(self):
        return f"{self.year} {self.manufacturer} {self.canonical_model}"

    @property
    def identity(self):
        return (self.year, normalize_car_text(self.manufacturer), normalize_car_text(self.canonical_model))


@dataclass(frozen=True)
class CatalogMatch:
    car: ProtectedCar
    confidence: float
    evidence: tuple


def C(year, make, model, *aliases, fe=False):
    return ProtectedCar(year, make, model, tuple(aliases), fe)


PROTECTED_CARS = (
    C(2019, "Apollo", "Intensa Emozione", "Apollo IE"),
    C(2019, "Aston Martin", "DBS Superleggera"),
    C(2019, "Aston Martin", "Valhalla Concept Car", "Valhalla Concept"),
    C(1984, "Audi", "Sport quattro"),
    C(2016, "Bentley", "Bentayga"),
    C(2020, "BMW", "M2 Competition Coupé", "M2 Competition Coupe", "M2 Competition"),
    C(2019, "Casey Currie Motorsports", "#4402 Ultra 4 'Trophy Jeep'", "4402 Ultra 4 Trophy Jeep"),
    C(1960, "Chevrolet", "Corvette"),
    C(2019, "Chevrolet", "Corvette ZR1"),
    C(1968, "Dodge", "Dart HEMI Super Stock"),
    C(1970, "Dodge", "Challenger R/T", "Challenger RT"),
    C(2016, "Dodge", "Viper ACR"),
    C(1984, "Ferrari", "288 GTO"),
    C(1992, "Ferrari", "512 TR"),
    C(1994, "Ferrari", "F355 Berlinetta"),
    C(2012, "Ferrari", "599XX Evolution", "599XX Evo"),
    C(2019, "Ferrari", "F8 Tributo"),
    C(1968, "Ford", "Mustang GT 2+2 Fastback Forza Edition", "Mustang GT 2 2 Fastback Forza Edition", fe=True),
    C(1986, "Ford", "F-150 XLT Lariat Forza Edition", "F150 XLT Lariat Forza Edition", fe=True),
    C(2014, "Ford", "Ranger T6 Rally Raid"),
    C(2017, "Ford", "M-Sport Fiesta RS", "M Sport Fiesta RS"),
    C(2020, "Ford", "Super Duty F-450 DRW PLATINUM Forza Edition", "Super Duty F450 DRW Platinum Forza Edition", fe=True),
    C(2022, "Ford", "F-150 Lightning", "F150 Lightning"),
    C(2006, "Formula Drift", "#43 Dodge Viper SRT-10 ACR", "43 Dodge Viper SRT10 ACR"),
    C(2015, "Formula Drift", "#13 Ford Mustang", "13 Ford Mustang"),
    C(2012, "Hennessey", "Venom GT"),
    C(1961, "Jaguar", "E-type", "E Type"),
    C(2015, "Koenigsegg", "One:1", "One 1"),
    C(1999, "Lamborghini", "Diablo GTR"),
    C(2011, "Lamborghini", "Sesto Elemento"),
    C(2012, "Lamborghini", "Aventador LP700-4", "Aventador LP700 4"),
    C(2021, "McLaren", "620R"),
    C(2018, "Mercedes-AMG", "GT 4-Door Coupé", "GT 4 Door Coupe", "Mercedes AMG GT 4 Door Coupe"),
    C(1990, "Mercedes-Benz", "190 E 2.5-16 Evolution II Forza Edition", "190 E 2 5 16 Evolution II Forza Edition", fe=True),
    C(1998, "Mercedes-Benz", "AMG CLK GTR", "CLK GTR", "Mercedes Benz AMG CLK GTR"),
    C(2014, "Mercedes-Benz", "G 63 AMG 6x6", "G63 AMG 6X6"),
    C(1989, "Nissan", "S-Cargo Forza Edition", "S Cargo Forza Edition", fe=True),
    C(1993, "Nissan", "240SX"),
    C(2012, "Nissan", "GT-R Black Edition (R35) Forza Edition", "GTR Black Edition R35 Forza Edition", fe=True),
    C(1970, "Porsche", "#3 917 LH Forza Edition", "3 917 LH Forza Edition", fe=True),
    C(1995, "Porsche", "911 GT2"),
    C(2019, "Porsche", "911 GT3 RS"),
    C(2021, "Rimac", "Nevera"),
    C(2021, "RJ Anderson", "#37 Polaris RZR Pro 4 Truck", "37 Polaris RZR Pro 4 Truck"),
    C(2013, "Wuling", "Sunshine S Forza Edition", fe=True),
)

PRIORITY_TARGETS = tuple(car.identity for car in PROTECTED_CARS if car.display_name in {
    "2019 Apollo Intensa Emozione", "2015 Koenigsegg One:1",
    "1998 Mercedes-Benz AMG CLK GTR", "2012 Hennessey Venom GT",
    "2012 Ferrari 599XX Evolution", "2011 Lamborghini Sesto Elemento",
    "2021 Rimac Nevera",
})


def _phrase_present(phrase, text):
    return f" {normalize_car_text(phrase)} " in f" {text} "


def identify_protected(raw_text):
    """Return an exact catalog match or None; partial OCR always fails closed."""
    text = normalize_car_text(raw_text)
    years = {int(value) for value in re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)}
    matches = []
    for car in PROTECTED_CARS:
        if years != {car.year} or not _phrase_present(car.manufacturer, text):
            # Mercedes-AMG cards may spell the maker as MERCEDES BENZ while
            # keeping AMG in the model line; accept only that explicit family.
            maker_alias = (car.manufacturer.startswith("Mercedes") and
                           _phrase_present("Mercedes Benz", text))
            if years != {car.year} or not maker_alias:
                continue
        aliases = (car.canonical_model, *car.known_display_aliases)
        matched = [alias for alias in aliases if _phrase_present(alias, text)]
        if matched:
            matches.append(CatalogMatch(car, 1.0, (str(car.year), car.manufacturer, matched[0])))
    return matches[0] if len(matches) == 1 else None


assert len(PROTECTED_CARS) == 45
assert len({car.identity for car in PROTECTED_CARS}) == 45
