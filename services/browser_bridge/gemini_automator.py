import os
import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Playwright, BrowserContext, Page

logger = logging.getLogger("gemini_automator")
logging.basicConfig(level=logging.INFO)

GEMINI_URL = "https://gemini.google.com/app"
DEFAULT_PROFILE_DIR = os.environ.get("BROWSER_PROFILE_DIR", "/data/browser_profile")
DEFAULT_HEADLESS = os.environ.get("ZEROGRAVITY_HEADLESS", "true").lower() == "true"


class GeminiAutomator:
    def __init__(self, profile_dir: str = DEFAULT_PROFILE_DIR, headless: bool = DEFAULT_HEADLESS):
        self.profile_dir = profile_dir
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._lock = asyncio.Lock()

    async def start(self):
        async with self._lock:
            if self.context:
                return
            logger.info(f"Starting Playwright with profile dir: {self.profile_dir}, headless: {self.headless}")
            os.makedirs(self.profile_dir, exist_ok=True)
            self.playwright = await async_playwright().start()
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 800},
            )
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            try:
                logger.info(f"Navigating browser to {GEMINI_URL}...")
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Initial navigation warning: {e}")

    async def stop(self):
        async with self._lock:
            if self.context:
                await self.context.close()
                self.context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self.page = None

    async def is_authenticated(self) -> bool:
        if not self.page:
            return False
        try:
            current_url = self.page.url
            if "accounts.google.com" in current_url:
                return False
            if current_url == "about:blank" or not current_url.startswith("https://gemini.google.com"):
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=15000)
            
            # Check for input box or sign in button
            selectors_authenticated = [
                'rich-textarea',
                'div[contenteditable="true"]',
                'textarea[aria-label*="Prompt"]',
                '.input-area',
                'p[data-placeholder]',
            ]
            for sel in selectors_authenticated:
                if await self.page.is_visible(sel):
                    return True
            
            # Check if sign in button is visible
            sign_in_selectors = [
                'a[href*="accounts.google.com"]',
                'button:has-text("Sign in")',
                'a:has-text("Sign in")',
            ]
            for sel in sign_in_selectors:
                if await self.page.is_visible(sel):
                    return False
            
            # Additional check after short wait
            await asyncio.sleep(2)
            for sel in selectors_authenticated:
                if await self.page.is_visible(sel):
                    return True
            return False
        except Exception as e:
            logger.warning(f"Error checking authentication: {e}")
            return False

    async def get_latest_response_text(self) -> str:
        """Extracts text from latest model response, natively piercing Shadow DOM."""
        if not self.page:
            return ""
        selectors = [
            'message-content',
            'model-response',
            '.model-response-text',
            'div.markdown',
            '.response-container-content',
            '.response-container',
        ]
        for sel in selectors:
            try:
                locator = self.page.locator(sel)
                count = await locator.count()
                if count > 0:
                    text = (await locator.last.inner_text()).strip()
                    # Ensure this is actual model response, not UI chrome or sidebar
                    if text and not text.startswith("About Gemini") and not text.startswith("Sign in"):
                        return text
            except Exception:
                pass
        return ""

    async def send_prompt(self, prompt_text: str, timeout: int = 120, new_chat: bool = False) -> str:
        async with self._lock:
            if not self.page:
                await self.start()

            # 1. Determine conversation context and prepare page
            if new_chat:
                logger.info("New chat requested by OpenWebUI. Navigating to fresh Gemini conversation...")
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(1.0)
                prev_response_count = 0
                previous_text = ""
            elif not self.page.url.startswith(GEMINI_URL):
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
                prev_response_count = await self.page.locator('message-content, model-response').count()
                previous_text = await self.get_latest_response_text()
            else:
                prev_response_count = await self.page.locator('message-content, model-response').count()
                previous_text = await self.get_latest_response_text()

            auth = await self.is_authenticated()
            if not auth:
                raise RuntimeError("User is not authenticated on Gemini Web. Manual login required.")

            # Locate chat input box
            input_selector = None
            candidate_selectors = [
                'rich-textarea div[contenteditable="true"]',
                'div[contenteditable="true"]',
                'rich-textarea',
                'textarea[aria-label*="Prompt"]',
            ]
            for sel in candidate_selectors:
                try:
                    await self.page.wait_for_selector(sel, timeout=5000, state="visible")
                    input_selector = sel
                    break
                except Exception:
                    continue

            if not input_selector:
                raise RuntimeError("Could not locate prompt input element on Gemini page.")

            # 2. Dismiss any overlay banners (cookie consent, "Stay signed out", "Got it", etc.)
            for dismiss_sel in [
                'button:has-text("Stay signed out")',
                'button:has-text("Got it")',
                'button:has-text("I agree")',
                'button:has-text("Accept all")',
                'button:has-text("Dismiss")',
                'button:has-text("Close")',
                '.banner-body button',
                '.cdk-overlay-container button',
            ]:
                try:
                    btn = self.page.locator(dismiss_sel).first
                    if await btn.is_visible(timeout=500):
                        await btn.click(force=True)
                        logger.info(f"Dismissed overlay banner via {dismiss_sel}")
                        await asyncio.sleep(0.3)
                except Exception:
                    pass

            # 3. Focus and insert prompt using native contenteditable command
            input_elem = self.page.locator(input_selector).first
            await input_elem.click(force=True, timeout=5000)
            await asyncio.sleep(0.2)

            # Insert text via execCommand which updates Angular/ProseMirror models reliably for any prompt size
            await self.page.evaluate("""(text) => {
                const el = document.querySelector('rich-textarea div[contenteditable="true"]') || document.querySelector('div[contenteditable="true"]');
                if (el) {
                    el.focus();
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, text);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""", prompt_text)
            await asyncio.sleep(0.5)

            # 4. Submit: click send button
            send_clicked = False
            for btn_sel in [
                'button[aria-label*="Send message"]',
                'button.send-button',
                'button[aria-label*="Send"]',
                'button[aria-label*="Submit"]',
                '.send-button-container button',
            ]:
                try:
                    btn = self.page.locator(btn_sel).first
                    if await btn.is_visible(timeout=1000):
                        disabled_attr = await btn.get_attribute("aria-disabled")
                        if disabled_attr == "true":
                            continue
                        await btn.click(force=True)
                        send_clicked = True
                        logger.info(f"Clicked send button: {btn_sel}")
                        break
                except Exception:
                    pass

            if not send_clicked:
                logger.info("Send button not clicked directly; pressing Enter.")
                await self.page.keyboard.press("Enter")

            logger.info(f"Prompt submitted (prev bubbles: {prev_response_count}). Waiting for new response stream...")

            # 5. Wait for stream to start and stabilize
            start_time = asyncio.get_event_loop().time()
            await asyncio.sleep(2.5)

            last_len = -1
            stable_count = 0
            raw_output = ""

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    current_count = await self.page.locator('message-content, model-response').count()

                    # In multi-turn chat, new bubble must appear (current_count > prev_response_count)
                    # On fresh chat (prev_response_count == 0), response is bubble 1 (current_count >= 1)
                    is_new_bubble = (current_count > prev_response_count) if prev_response_count > 0 else (current_count >= 1)

                    if is_new_bubble:
                        current_text = await self.get_latest_response_text()
                        if current_text and (prev_response_count == 0 or current_text != previous_text):
                            curr_len = len(current_text.strip())
                            if curr_len > 0 and curr_len == last_len:
                                stable_count += 1
                                if stable_count >= 3:
                                    logger.info(f"Response stream finished (stabilized at {curr_len} chars, bubble {current_count}).")
                                    raw_output = current_text
                                    break
                            else:
                                last_len = curr_len
                                stable_count = 0
                except Exception as e:
                    logger.debug(f"Error checking text stability: {e}")

                await asyncio.sleep(1.0)

            if not raw_output:
                candidate_text = await self.get_latest_response_text()
                if candidate_text and candidate_text != previous_text:
                    logger.warning("Stream loop finished without stabilization count 3, but found new response text.")
                    raw_output = candidate_text
                else:
                    raise TimeoutError(f"Timed out after {timeout}s waiting for Gemini response stream to complete.")

            return raw_output.strip()

