import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
async def test_dashboard_discovery_on_load(dashboard_server):
    """
    Verify that the dashboard correctly discovers and displays mock trajectories on load.
    Using manual async_playwright context to ensure strict event loop isolation in Python 3.14.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(dashboard_server)

        # 1. Wait for Streamlit to hydrate (Industrial v2.1 Hardening)
        await page.wait_for_selector("section[data-testid='stSidebar']", timeout=10000)

        # 2. Verify Page Title
        await expect(page).to_have_title("AgentV Lab")

        # 3. Verify discovery of mock data
        await expect(page.get_by_text("Select Evaluation Run")).to_be_visible()

        # 4. Assert on the Success Rate Metric Card
        success_card = page.locator("div[data-testid='stMetric']").filter(has_text="Success Rate")
        await expect(success_card.locator("div[data-testid='stMetricValue']")).to_contain_text(
            "100.0%"
        )

        # 5. Assert on Task ID and Mermaid map
        await expect(page.get_by_text("Decision Trajectory Map")).to_be_visible()
        await expect(page.locator("code.language-mermaid")).to_be_visible()

        await browser.close()
