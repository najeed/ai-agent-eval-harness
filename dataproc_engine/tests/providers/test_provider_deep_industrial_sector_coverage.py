from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataproc_engine.core.base_provider import RawArtifact, StandardSchema
from dataproc_engine.providers.agriculture import AgricultureProvider
from dataproc_engine.providers.ecommerce import EcommerceProvider
from dataproc_engine.providers.education import EducationProvider
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.providers.manufacturing import ManufacturingProvider
from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
from dataproc_engine.providers.public_sector.housing import HousingProvider
from dataproc_engine.providers.public_sector.labor import LaborProvider
from dataproc_engine.providers.telecom import TelecomProvider
from dataproc_engine.providers.transportation import TransportationProvider
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.strategy = "mock"
    llm._verify_schema.side_effect = lambda data, schema, strict=False: data
    llm.extract_structured_data = AsyncMock(return_value={"entity_name": "Test", "revenue": 100})
    llm._heuristic_sentiment.return_value = 0.5
    llm.analyze_sentiment = AsyncMock(return_value=0.5)
    return llm


@pytest.mark.asyncio
async def test_agriculture_usda_and_heuristic_coverage(mock_llm):
    # 1. USDA mode + Simulation
    config = {"agriculture_mode": "usda", "allow_simulation": True}
    provider = AgricultureProvider(config, llm_manager=mock_llm)
    artifacts = await provider.extract()
    assert len(artifacts) > 0

    # 2. FAOStat mode + Climate Anomaly + Transform
    config_fao = {"agriculture_mode": "faostat", "climate_anomaly": 2.0}
    p_fao = AgricultureProvider(config_fao, llm_manager=mock_llm)
    mock_raw = MagicMock(spec=RawArtifact)
    mock_raw.content = [{"Area": "World", "Item": "Wheat", "Year": 2022, "Value": 100}]
    mock_raw.source_url = "http://fao.org"

    res = await p_fao.transform([mock_raw])
    assert len(res) == 1
    # 100 * (1 - 2*0.05) = 90
    assert res[0].data["value"] == 90.0
    assert "climate anomaly" in res[0].data["note"]

    # 3. Validation
    assert p_fao.validate(res) is True
    res[0].data["value"] = -1
    assert p_fao.validate(res) is False


@pytest.mark.asyncio
async def test_ecommerce_extract_failures_and_validation(mock_llm):
    config = {
        "ecommerce_mode": "tabular",
        "allow_simulation": False,
        "input_uri": "http://fail.com",
    }
    provider = EcommerceProvider(config, llm_manager=mock_llm)
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 404
        artifacts = await provider.extract()
        assert artifacts == []


@pytest.mark.asyncio
async def test_education_validation_failures(mock_llm):
    provider = EducationProvider({"education_mode": "nces"}, llm_manager=mock_llm)
    r1 = StandardSchema(
        id="1", industry="edu", data={"literacy_rate": 150}, provenance={}, checksum="x"
    )
    assert provider.validate([r1]) is False


@pytest.mark.asyncio
async def test_energy_coverage_gaps(mock_llm):
    provider = EnergyProvider(
        {"energy_mode": "opsd", "allow_simulation": False}, llm_manager=mock_llm
    )
    assert await provider.extract() == []


@pytest.mark.asyncio
async def test_finance_deep_coverage(mock_llm):
    # 1. WorldBank + simulation
    provider = FinanceProvider(
        {"finance_mode": "worldbank", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("API Down")):
        artifacts = await provider.extract()
        assert len(artifacts) > 0

    # 2. Credit Risk + Simulation
    p_cr = FinanceProvider(
        {"finance_mode": "credit_risk", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_cr = await p_cr.extract()
    res_cr = await p_cr.transform(arts_cr)
    assert len(res_cr) > 0

    # 3. SEC Edgar + Simulation + XBRL Fact Handling
    p_sec = FinanceProvider(
        {"finance_mode": "sec_edgar", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_sec = await p_sec.extract()
    # Mock XBRL fact structure
    arts_sec[0].content = {
        "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 5000, "fy": 2023}]}}}}
    }
    res_sec = await p_sec.transform(arts_sec)
    assert res_sec[0].data["total_assets"] == 5000

    # 4. Validation
    assert p_sec.validate(res_sec) is True
    res_sec[0].data["total_assets"] = -1
    assert p_sec.validate(res_sec) is False


@pytest.mark.asyncio
async def test_healthcare_validation_and_failures(mock_llm):
    # 1. WHO mode + Simulation
    p_who = HealthcareProvider(
        {"healthcare_mode": "who", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_who = await p_who.extract()
    assert len(arts_who) > 0

    # 2. CMS mode + PII scrubbing
    p_cms = HealthcareProvider(
        {"healthcare_mode": "cms", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_cms = await p_cms.extract()
    arts_cms[0].content = [{"Hospital Name": "Mercy <mercy@test.com>", "Provider ID": "001"}]
    res_cms = await p_cms.transform(arts_cms)
    assert "[EMAIL]" in res_cms[0].data["facility_name"]
    assert len(await p_cms.transform(arts_who)) > 0  # WHO transformation

    # 3. Validation
    provider = HealthcareProvider({"healthcare_mode": "clinical"}, llm_manager=mock_llm)
    r1 = StandardSchema(
        id="1", industry="hc", data={"subject_id": None}, provenance={}, checksum="x"
    )
    assert provider.validate([r1]) is False


@pytest.mark.asyncio
async def test_manufacturing_industrial_and_asm(mock_llm):
    # 1. ASM mode (Census list format)
    p_asm = ManufacturingProvider(
        {"manufacturing_mode": "asm", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts = await p_asm.extract()
    res = await p_asm.transform(arts)
    assert len(res) > 0
    assert "Food manufacturing" in res[0].data["industry_label"]

    # 2. Industrial Stats + Validation
    p_ind = ManufacturingProvider(
        {"manufacturing_mode": "industrial_stats", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_ind = await p_ind.extract()
    res_ind = await p_ind.transform(arts_ind)
    assert len(res_ind) > 0
    assert p_ind.validate(res_ind) is True
    res_ind[0].data["mva_value"] = -1
    assert p_ind.validate(res_ind) is False

    # 3. No sim branch
    p1 = ManufacturingProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p1.extract() == []


@pytest.mark.asyncio
async def test_demographics_and_housing_gaps(mock_llm):
    p1 = DemographicsProvider(
        {"demographics_mode": "worldbank", "allow_simulation": False}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 404
        assert await p1.extract() == []
    p2 = HousingProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p2.extract() == []


@pytest.mark.asyncio
async def test_labor_and_telecom_coverage(mock_llm):
    p1 = LaborProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p1.extract() == []

    # 1. FCC mode + PII Scrubbing
    p2 = TelecomProvider({"telecom_mode": "fcc", "allow_simulation": True}, llm_manager=mock_llm)
    arts = await p2.extract()
    arts[0].content = [
        {"provider_name": "Test <test@test.com>", "max_ad_down": 100, "max_ad_up": 20}
    ]
    res = await p2.transform(arts)
    assert "[EMAIL]" in res[0].data["provider_name"]

    # 2. Ookla and ITU modes
    p_o = TelecomProvider({"telecom_mode": "ookla", "allow_simulation": True}, llm_manager=mock_llm)
    assert len(await p_o.extract()) > 0
    p_i = TelecomProvider({"telecom_mode": "itu", "allow_simulation": True}, llm_manager=mock_llm)
    assert len(await p_i.extract()) > 0

    # 3. Validation
    assert p2.validate(res) is True
    res[0].data["download_speed"] = -1
    assert p2.validate(res) is False


@pytest.mark.asyncio
async def test_transportation_osm_and_eurostat(mock_llm):
    # 1. OSM mode + Simulation
    p_osm = TransportationProvider(
        {"transit_mode": "osm", "allow_simulation": True}, llm_manager=mock_llm
    )
    # Mock aiohttp to force simulation or failure
    with patch("aiohttp.ClientSession.get", side_effect=Exception("API Down")):
        arts = await p_osm.extract()
        assert len(arts) > 0
        res = await p_osm.transform(arts)
        assert res[0].data["name"] == "Global Way"

    # 2. Eurostat mode
    p_euro = TransportationProvider(
        {"transit_mode": "eurostat", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_e = await p_euro.extract()
    res_e = await p_euro.transform(arts_e)
    assert len(res_e) > 0

    # 3. DOT BTS mode (Airline)
    p_air = TransportationProvider(
        {"transit_mode": "air", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_a = await p_air.extract()
    res_a = await p_air.transform(arts_a)
    assert res_a[0].data["entity"] == "AA"

    # 3.1 Airline validation
    assert p_air.validate(res_a) is True
    res_a[0].data["metric_value"] = -1
    assert p_air.validate(res_a) is False

    # 4. Validation
    assert p_osm.validate(res) is True
    res[0].data["metric_value"] = 150  # Out of range 0-100
    p_air = TransportationProvider({"transit_mode": "air"}, llm_manager=mock_llm)
    assert p_air.validate(res) is False


@pytest.mark.asyncio
async def test_unstructured_provider_deep_logic(mock_llm, tmp_path):
    p = UnstructuredProvider(
        {"input_uri": "http://fail.com", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 500
        artifacts = await p.extract()
        assert "CC-" in artifacts[0].id

    # 1. Local Text File + Heuristic Pivot
    test_file = tmp_path / "doc.txt"
    test_file.write_text("Acquisition of AI startup was a success.")
    p_txt = UnstructuredProvider(
        {"input_uri": str(test_file), "industry": "tech"}, llm_manager=mock_llm
    )

    # Trigger fallback by having LLM return None
    mock_llm.extract_structured_data.return_value = None

    arts_txt = await p_txt.extract()
    res_txt = await p_txt.transform(arts_txt)
    assert len(res_txt) > 0
    assert "M&A_ACTIVITY" in res_txt[0].data["strategic_signals"]
    assert res_txt[0].data["sentiment_score"] == 0.5  # from mock_llm fixture

    # 2. PDF Extraction Mocking
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_text("%PDF-1.4 test content")
    p_pdf = UnstructuredProvider({"input_uri": str(pdf_file)}, llm_manager=mock_llm)

    with patch("pypdf.PdfReader") as mock_pdf:
        mock_reader = mock_pdf.return_value
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF Content"
        mock_reader.pages = [mock_page]
        mock_reader.metadata = MagicMock(author="Tester")

        arts_pdf = await p_pdf.extract()
        assert "PDF Content" in arts_pdf[0].content

    # 3. Image/OCR Mocking
    img_file = tmp_path / "test.png"
    img_file.write_text("fake image content")
    p_img = UnstructuredProvider({"input_uri": str(img_file)}, llm_manager=mock_llm)

    import sys

    with patch.dict(sys.modules, {"pytesseract": MagicMock(), "PIL": MagicMock()}):
        import pytesseract

        pytesseract.image_to_string.return_value = "OCR Text"
        arts_img = await p_img.extract()
        assert "OCR Text" in arts_img[0].content

    # 4. Common Crawl Transformation
    p_cc = UnstructuredProvider({"unstructured_mode": "common_crawl"}, llm_manager=mock_llm)
    arts_cc = await p_cc.extract()
    res_cc = await p_cc.transform(arts_cc)
    assert "Global AI Trends" in res_cc[0].data["web_title"]

    # 5. Edge cases: Missing URI, Read failure, Integrity fail
    p_none = UnstructuredProvider({"allow_simulation": True}, llm_manager=mock_llm)
    assert len(await p_none.extract()) > 0  # generic sim

    p_fail = UnstructuredProvider({"input_uri": "nonexistent.txt"}, llm_manager=mock_llm)
    assert await p_fail.extract() == []

    # Integrity fail
    mock_llm._verify_domain_integrity.return_value = False  # Wait, it's a provider method
    p_txt.config["industry"] = "tech"
    # To hit integrity fail, we need a negative revenue
    mock_llm.extract_structured_data.return_value = {"revenue": -100, "entity_name": "Test"}
    assert await p_txt.transform(arts_txt) == []

    # Sentiment analysis branch
    mock_llm.extract_structured_data.return_value = {"entity_name": "Test"}
    res_sent = await p_txt.transform(arts_txt)
    assert res_sent[0].data["sentiment_score"] == 0.5


@pytest.mark.asyncio
async def test_provider_deep_hardening_failure_modes(mock_llm, tmp_path):
    # --- Agriculture Hardening ---
    p_ag = AgricultureProvider(
        {"agriculture_mode": "usda", "allow_simulation": True}, llm_manager=mock_llm
    )
    # Force API failure to hit bottom simulation block
    with patch("aiohttp.ClientSession.get", side_effect=Exception("API Fail")):
        with patch("os.path.exists", return_value=False):
            arts = await p_ag.extract()
            assert "usda" in arts[0].id.lower()
            # Transformation loop for simulation
            res = await p_ag.transform(arts)
            assert len(res) > 0

    # FAOStat transform loop branch
    p_fao = AgricultureProvider({"agriculture_mode": "faostat"}, llm_manager=mock_llm)
    mock_llm._verify_schema.side_effect = None
    mock_llm._verify_schema.return_value = None
    res = await p_fao.transform(
        [
            RawArtifact(
                id="f",
                content=[{"Area": "X"}],
                source_url="u",
                metadata={},
                timestamp="2023-01-01",
            )
        ]
    )
    assert res == []
    mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # --- Finance Hardening ---
    p_fi = FinanceProvider(
        {"finance_mode": "worldbank", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Fail")):
        arts = await p_fi.extract()
        assert "WB" in arts[0].id

    # WorldBank non-dict row and verify_schema None
    arts[0].content = [{"page": 1}, ["not-a-dict"], {"value": 100}]
    mock_llm._verify_schema.side_effect = None
    mock_llm._verify_schema.return_value = None
    res_fi = await p_fi.transform(arts)
    assert len(res_fi) == 0
    mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # SEC EDGAR Simulation without mock file
    p_sec = FinanceProvider(
        {"finance_mode": "sec_edgar", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("SEC Fail")):
        with patch("os.path.exists", return_value=False):
            arts_sec = await p_sec.extract()
            assert "SEC" in arts_sec[0].id
            # SEC Transform skip
            mock_llm._verify_schema.side_effect = None
            mock_llm._verify_schema.return_value = None
            assert await p_sec.transform(arts_sec) == []
            mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # Validation failures
    r_fail = StandardSchema(
        id="f", industry="finance", data={"limit_balance": -100}, provenance={}, checksum="x"
    )
    p_cr = FinanceProvider({"finance_mode": "credit_risk"}, llm_manager=mock_llm)
    assert p_cr.validate([r_fail]) is False

    r_wb_fail = StandardSchema(
        id="f", industry="finance", data={"value": None}, provenance={}, checksum="x"
    )
    p_wb = FinanceProvider({"finance_mode": "worldbank"}, llm_manager=mock_llm)
    assert p_wb.validate([r_wb_fail]) is False

    # --- Healthcare Hardening ---
    p_hc = HealthcareProvider(
        {"healthcare_mode": "who", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get") as m_get:
        m_get.return_value.__aenter__.return_value.status = 500
        arts = await p_hc.extract()
        assert "WHO" in arts[0].id
        # WHO Transform skip
        mock_llm._verify_schema.side_effect = None
        mock_llm._verify_schema.return_value = None
        assert await p_hc.transform(arts) == []
        mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # Clinical simulation
    p_clin = HealthcareProvider(
        {"healthcare_mode": "clinical", "allow_simulation": True}, llm_manager=mock_llm
    )
    arts_clin = await p_clin.extract()
    assert "CLIN" in arts_clin[0].id
    mock_llm._verify_schema.side_effect = None
    mock_llm._verify_schema.return_value = None
    assert await p_clin.transform(arts_clin) == []
    mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # CMS Validation failure
    r_hc_fail = StandardSchema(
        id="f", industry="healthcare", data={"facility_name": ""}, provenance={}, checksum="x"
    )
    assert p_hc.validate([r_hc_fail]) is False

    # --- Manufacturing Hardening ---
    # ASM Dictionary format (hit get_f)
    p_asm = ManufacturingProvider({"manufacturing_mode": "asm"}, llm_manager=mock_llm)
    # Pass list-of-lists format with header to hit is_list_format
    raw_asm = RawArtifact(
        id="asm",
        content=[
            ["Label", "Estab", "Emp", "Pay", "Ship"],
            ["Test", 10, 5, 100, 500],
        ],
        source_url="u",
        metadata={},
        timestamp="2023-01-01",
    )
    res = await p_asm.transform([raw_asm])
    assert res[0].data["industry_label"] == "Test"

    # ASM verify_schema None
    mock_llm._verify_schema.side_effect = None
    mock_llm._verify_schema.return_value = None
    assert await p_asm.transform([raw_asm]) == []
    mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # --- Telecom Hardening ---
    # ITU simulation
    p_itu = TelecomProvider({"telecom_mode": "itu", "allow_simulation": True}, llm_manager=mock_llm)
    with patch("aiohttp.ClientSession.get", side_effect=Exception("ITU Fail")):
        arts_itu = await p_itu.extract()
        assert "ITU" in arts_itu[0].id

    # Ookla simulation
    p_ook = TelecomProvider(
        {"telecom_mode": "ookla", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Ookla Fail")):
        arts_ook = await p_ook.extract()
        assert "OOKLA" in arts_ook[0].id

    # FCC Extraction failure and transform
    p_tel = TelecomProvider({"telecom_mode": "fcc", "allow_simulation": True}, llm_manager=mock_llm)
    with patch("aiohttp.ClientSession.get", side_effect=Exception("FCC Error")):
        arts = await p_tel.extract()
        assert "sim-FCC" in arts[0].id
        res_tel = await p_tel.transform(arts)
        assert len(res_tel) > 0

    # --- Transportation Hardening ---
    # DOT-BTS Extraction failure and simulation
    p_dot = TransportationProvider(
        {"transit_mode": "air", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("DOT Fail")):
        with patch("os.path.exists", return_value=False):
            arts_dot = await p_dot.extract()
            assert "sim-BTS" in arts_dot[0].id
            # Transform skip
            mock_llm._verify_schema.side_effect = None
            mock_llm._verify_schema.return_value = None
            assert await p_dot.transform(arts_dot) == []
            mock_llm._verify_schema.side_effect = lambda d, s, strict=False: d

    # OSM Validation fail
    r_osm_fail = StandardSchema(
        id="f", industry="transportation", data={"id": None}, provenance={}, checksum="x"
    )
    p_osm = TransportationProvider({"transit_mode": "osm"}, llm_manager=mock_llm)
    assert p_osm.validate([r_osm_fail]) is False

    # --- Unstructured Hardening ---
    # Directory with no files
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    p_uns = UnstructuredProvider({"input_uri": str(empty_dir)}, llm_manager=mock_llm)
    assert await p_uns.extract() == []

    # Read failure
    fail_file = tmp_path / "fail.txt"
    fail_file.write_text("...")
    p_fail = UnstructuredProvider({"input_uri": str(fail_file)}, llm_manager=mock_llm)
    with patch("builtins.open", side_effect=Exception("Read Fail")):
        assert await p_fail.extract() == []

    # Heuristic: MARKET_HEADWINDS
    res = p_uns._derive_strategic_pivot("Significant decline in market share and risk factors.")
    assert "MARKET_HEADWINDS" in res

    # OCR Failure branch
    img_file = tmp_path / "fail.png"
    img_file.write_text("...")
    p_img = UnstructuredProvider({"input_uri": str(img_file)}, llm_manager=mock_llm)
    with patch.dict("sys.modules", {"pytesseract": MagicMock(), "easyocr": MagicMock()}):
        # We need to ensure EasyOCR also fails or isn't used
        with patch("easyocr.Reader", side_effect=Exception("OCR Fail")):
            arts = await p_img.extract()
            assert arts == []
