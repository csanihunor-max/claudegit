from hardverapro_arbitrage.scraper.gpu_specs import GpuSpec, parse_gpu_spec


# Every title below is a real one pulled from hardverapro.hu's own
# "Graphics Cards" category in the scraped database.
def test_parses_nvidia_rtx_with_space_before_variant_suffix():
    assert parse_gpu_spec("BESZÁMÍTÁS! Asus ROG Strix RTX 3070 8GB videokártya garanciával") == GpuSpec("rtx3070", 8)
    assert parse_gpu_spec("ASUS ROG Strix GeForce RTX 3060 Ti 8 GB GDDR6 Gaming videokártya") == GpuSpec("rtx3060ti", 8)


def test_parses_nvidia_rtx_with_suffix_glued_to_model_number():
    # "3070Ti" with no space at all -- a real, common seller style.
    assert parse_gpu_spec("Gigabyte Aorus Master RTX 3070Ti 8GB videokártya garanciával") == GpuSpec("rtx3070ti", 8)


def test_parses_nvidia_gtx_and_gt():
    assert parse_gpu_spec("BESZÁMÍTÁS! Asus ROG Strix GTX 1050Ti 4GB videokártya garanciával") == GpuSpec(
        "gtx1050ti", 4
    )
    assert parse_gpu_spec("ASUS TUF Gaming GeForce GTX 1660 SUPER OC EDITION 6GB GDDR6 GAMING Videokártya") == GpuSpec(
        "gtx1660super", 6
    )
    # "GT720" glued with no space -- must not get confused with "GTX".
    assert parse_gpu_spec("MSI GT720 2GB GDDR5 Low Profile SFF videokártya") == GpuSpec("gt720", 2)


def test_parses_amd_rx_with_and_without_variant():
    assert parse_gpu_spec("SAPPHIRE Radeon RX 9070 XT PULSE 16GB GDDR6 256bit videokártya") == GpuSpec("rx9070xt", 16)
    assert parse_gpu_spec("27% - SAPPHIRE RX 7900 XTX Nitro+ 24GB DDR6 Nitro+ Videokártya!") == GpuSpec("rx7900xtx", 24)
    assert parse_gpu_spec("SAPPHIRE Radeon RX570 4GB NITRO+ videokártya") == GpuSpec("rx570", 4)
    # "RX5700XT" fully glued, no spaces anywhere.
    assert parse_gpu_spec("Videokártya Sapphire Nitro+ RX5700XT 8GB") == GpuSpec("rx5700xt", 8)


def test_parses_older_amd_r_series_naming():
    assert parse_gpu_spec("Asus Radeon R7 250 2GB videokártya eladó (Hibamentes, megkímélt állapotban)") == GpuSpec(
        "r7250", 2
    )
    assert parse_gpu_spec("ASUS STRIX R9 380 DirectCU II OC 4 GB videokártya") == GpuSpec("r9380", 4)


def test_does_not_match_a_same_looking_ryzen_cpu_name():
    # "R5 5600X" is a CPU, not a 3-digit R-series Radeon GPU -- the 4-digit
    # model number is what must keep this from matching.
    assert parse_gpu_spec("AMD Ryzen R5 5600X processzor") is None


def test_excludes_nvidia_professional_workstation_naming():
    # Real titles from the DB (laptops/workstations, not standalone
    # cards) -- RTX A4500/ADA 2000/PRO 2000 are a different product line
    # priced completely differently from consumer RTX 30/40/50-series
    # cards that happen to share the same trailing numbers.
    assert parse_gpu_spec("Dell Precision 7770 ... RTX A4500 16G ...") is None
    assert parse_gpu_spec("DELL Precision 5680 ... RTX ADA 2000 8GB VGA! Garancia") is None
    assert parse_gpu_spec("Pro Max MC14250 ... RTX Pro 500 32GB 1TB NVMe") is None


def test_returns_none_without_a_recognized_chip():
    assert parse_gpu_spec("MSI Cmp 30 hx videokártya eladó") is None


def test_returns_none_without_vram():
    assert parse_gpu_spec("Eladó RTX 3070 videokártya garanciával") is None
