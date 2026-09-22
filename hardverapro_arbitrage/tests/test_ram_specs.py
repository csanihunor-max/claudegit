from hardverapro_arbitrage.scraper.ram_specs import RamSpec, parse_ram_spec


# Every title below is a real one pulled from the scraped database --
# grounding the regexes in actual seller phrasing rather than guesses.
def test_parses_kit_notation():
    assert parse_ram_spec("CORSAIR VENGEANCE LPX 16GB (2x8GB) DDR4 3200MHz /CMK16GX4M2B3200C16R/ - DOBOZOS !") == RamSpec(
        "ddr4", 16, 3200
    )
    assert parse_ram_spec("G.SKILL Ripjaws V 32GB (2x16GB) DDR4 3200MHz CL16") == RamSpec("ddr4", 32, 3200)
    assert parse_ram_spec("HyperX Fury RGB 32 GB kit (4x8 GB) DDR4 3000 MHz CL15") == RamSpec("ddr4", 32, 3000)


def test_parses_plain_capacity_without_kit_notation():
    assert parse_ram_spec("G.SKILL Aegis 16 GB DDR4-3200 CL16 memória (1x16)") == RamSpec("ddr4", 16, 3200)
    assert parse_ram_spec("Kingston DDR4 8GB asztali RAM 2400MHz TÖBB DARAB- 1 év garancia + számla") == RamSpec(
        "ddr4", 8, 2400
    )


def test_parses_hyphenated_ddr_frequency_shorthand():
    # "DDR4-3200" style naming states the frequency with no unit word at
    # all -- real false negative this guards against: an earlier version
    # only looked for a number tagged with "mhz"/"mt/s" and missed this
    # entirely.
    assert parse_ram_spec("2x32GB Crucial DDR4-3200 memória") == RamSpec("ddr4", 64, 3200)


def test_parses_mts_unit():
    assert parse_ram_spec("PATRIOT VIPER VENOM DDR5 32GB (2X16GB) 7400MT/s UDIMM KIT") == RamSpec("ddr5", 32, 7400)


def test_kit_total_overrides_bare_number_when_both_present():
    # "16GB (2x8GB)" -- the leading 16 and the kit math agree here, but
    # the kit pattern is checked first regardless so a title where they
    # *don't* agree (a typo, or capacity meaning something else) still
    # reports the actual per-stick-count-derived total.
    assert parse_ram_spec("Corsair Vengeance LPX 32GB kit (2x16GB) 2133MHz C13 DDR4").capacity_gb == 32


def test_returns_none_without_a_ddr_generation():
    assert parse_ram_spec("32GB 3200MHz memória, márka nélkül") is None


def test_returns_none_without_a_frequency():
    assert parse_ram_spec("Kingston DDR4 16GB RAM garanciával") is None


def test_returns_none_without_a_capacity():
    assert parse_ram_spec("Kingston DDR4 3200MHz RAM garanciával") is None


def test_does_not_misread_a_laptops_embedded_ram_as_a_frequency_match():
    # Real title from the DB: mentions "ddr4" and "16gb" but never states
    # an MHz/MT/s figure at all for the laptop's RAM -- must not invent
    # one from an unrelated number elsewhere in the title (a CPU model,
    # a screen size, ...).
    assert parse_ram_spec("Dell Latitude 5420 11. gen Core i5-1145G7, 5410 10.gen, 16 Gb ddr4, nvme ssd") is None
