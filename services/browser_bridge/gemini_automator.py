import os
import time
import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Playwright, BrowserContext, Page

logger = logging.getLogger("gemini_automator")
logging.basicConfig(level=logging.INFO)

GEMINI_URL = "https://gemini.google.com/app"
DEFAULT_PROFILE_DIR = os.environ.get("BROWSER_PROFILE_DIR", "/data/browser_profile")
DEFAULT_HEADLESS = os.environ.get("ZEROGRAVITY_HEADLESS", "true").lower() == "true"
DEFAULT_EXECUTABLE_PATH = os.environ.get("BROWSER_EXECUTABLE_PATH") or os.environ.get("ZEROGRAVITY_BROWSER_EXECUTABLE")
DEFAULT_CHANNEL = os.environ.get("BROWSER_CHANNEL") or os.environ.get("ZEROGRAVITY_BROWSER_CHANNEL")
# Max seconds to wait for Gemini to finish streaming a response (long multi-file answers can take minutes)
DEFAULT_RESPONSE_TIMEOUT = int(os.environ.get("GEMINI_RESPONSE_TIMEOUT", "240"))
# Where screenshots / HTML dumps are saved when a prompt fails (workspace is mounted into the bridge container)
DEFAULT_DEBUG_DIR = os.environ.get("BRIDGE_DEBUG_DIR", "/workspace/.gemini-history/bridge_debug")

# Model response containers, most specific first
RESPONSE_SELECTORS = [
    'model-response message-content',
    'model-response .markdown',
    'message-content',
    '[id^="model-response-message-content"]',
    '.model-response-text',
    'model-response',
    '.response-container-content',
    '#chat-history .markdown',
]
# Count one element per model turn (avoid double counting nested model-response > message-content)
RESPONSE_COUNT_SELECTORS = (
    'model-response',
    'message-content',
    '#chat-history .markdown',
)
USER_QUERY_SELECTOR = 'user-query, .user-query-container, [data-test-id="user-query"]'
# Visible while Gemini is still generating
STOP_BUTTON_SELECTORS = [
    'button[aria-label*="Stop response"]',
    'button[aria-label*="Stop generating"]',
    'button[aria-label*="Stop"]',
]
# Known Gemini-side failure messages surfaced in the page
GEMINI_ERROR_MARKERS = [
    "Something went wrong",
    "I'm having a hard time fulfilling your request",
    "You've reached your limit",
    "reached the limit",
    "Try again later",
    "unusual traffic",
]

# Consent buttons that trigger a page reload / redirect when clicked
CONSENT_BUTTON_SELECTORS = [
    'cookie-banner button[data-test-id="accept-button"]',
    'button[data-test-id="accept-button"]',
    'cookie-banner button[data-test-id="reject-button"]',
    'button[data-test-id="reject-button"]',
    'cookie-banner button:has-text("Accept all")',
    'cookie-banner button:has-text("Reject all")',
    'button:has-text("Accept all")',
    'button:has-text("I agree")',
]

# In-page banners/popups that close without reloading the page
DISMISS_BUTTON_SELECTORS = [
    'button:has-text("Stay signed out")',
    'button:has-text("Got it")',
    'button:has-text("Dismiss")',
    'button:has-text("No thanks")',
    'button[aria-label="Close"]',
    'button:has-text("Close")',
]


class GeminiAutomator:
    def __init__(
        self,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        headless: bool = DEFAULT_HEADLESS,
        executable_path: Optional[str] = DEFAULT_EXECUTABLE_PATH,
        channel: Optional[str] = DEFAULT_CHANNEL,
        debug_dir: str = DEFAULT_DEBUG_DIR,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.executable_path = executable_path
        self.channel = channel
        self.debug_dir = debug_dir
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._lock = asyncio.Lock()

    async def start(self):
        async with self._lock:
            await self._start_unlocked()

    async def _start_unlocked(self):
        """Launches the browser. Caller must hold self._lock (asyncio.Lock is not re-entrant)."""
        if self.context:
            return
        logger.info(
            f"Starting Playwright with profile dir: {self.profile_dir}, "
            f"headless: {self.headless}, "
            f"executable_path: {self.executable_path}, "
            f"channel: {self.channel}"
        )
        os.makedirs(self.profile_dir, exist_ok=True)
        self.playwright = await async_playwright().start()

        launch_kwargs = {
            "user_data_dir": self.profile_dir,
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            "viewport": {"width": 1280, "height": 800},
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        if self.channel:
            launch_kwargs["channel"] = self.channel

        self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        try:
            logger.info(f"Navigating browser to {GEMINI_URL}...")
            await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            await self._dismiss_overlays()
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

    async def _dismiss_overlays(self) -> bool:
        """
        Dismisses Google cookie consent modals ("Before you continue to Google")
        and in-page popups ("Stay signed out", "Got it", etc.).
        Uses DOM .click() so buttons scrolled below the fold inside .cookie-banner are reliably triggered.
        """
        if not self.page:
            return False
        dismissed_any = False

        # 1. Cookie consent modal (may trigger consent.google.com redirect & page reload)
        for sel in CONSENT_BUTTON_SELECTORS:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0:
                    await loc.evaluate("el => el.click()")
                    logger.info(f"Accepted/dismissed cookie consent modal via {sel}")
                    dismissed_any = True
                    await asyncio.sleep(1.5)
                    try:
                        await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    # Wait for the modal backdrop to disappear
                    for _ in range(10):
                        if await self.page.locator("cookie-banner, .cdk-overlay-backdrop-showing").count() == 0:
                            break
                        await asyncio.sleep(0.5)
                    break
            except Exception as e:
                logger.debug(f"Consent selector {sel} check failed: {e}")

        # 2. Non-navigating dismissable banners/popups
        for sel in DISMISS_BUTTON_SELECTORS:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.evaluate("el => el.click()")
                    logger.info(f"Dismissed overlay banner via {sel}")
                    dismissed_any = True
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        return dismissed_any

    async def is_signed_in(self) -> bool:
        """Returns True if the browser profile is logged into a Google account (not guest/signed-out mode)."""
        if not self.page:
            return False
        try:
            if "accounts.google.com" in self.page.url:
                return False
            if await self.page.locator("body.viewer-signed-out").count() > 0:
                return False
            for sel in (
                'a[aria-label="Sign in"]',
                'a[href*="accounts.google.com/ServiceLogin"]',
                'button[data-test-id="sign-in-button"]',
            ):
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return False
            return True
        except Exception:
            return False

    async def is_authenticated(self) -> bool:
        """
        Returns True if Gemini Web's chat prompt is reachable and ready to accept input
        (works for both signed-in accounts and signed-out guest sessions after cookie consent).
        """
        if not self.page:
            return False
        try:
            current_url = self.page.url
            if "accounts.google.com" in current_url:
                return False
            if current_url == "about:blank" or not current_url.startswith("https://gemini.google.com"):
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.0)

            await self._dismiss_overlays()

            # If a modal backdrop is still covering the page, the input cannot be used
            if await self.page.locator("cookie-banner, .cdk-overlay-backdrop-showing").count() > 0:
                await self._dismiss_overlays()

            selectors_ready = [
                'rich-textarea div[contenteditable="true"]',
                'rich-textarea',
                'div[contenteditable="true"]',
                'textarea[aria-label*="Prompt"]',
                '.input-area',
            ]
            for sel in selectors_ready:
                if await self.page.is_visible(sel):
                    return True

            await asyncio.sleep(1.5)
            await self._dismiss_overlays()
            for sel in selectors_ready:
                if await self.page.is_visible(sel):
                    return True
            return False
        except Exception as e:
            logger.warning(f"Error checking readiness/authentication: {e}")
            return False

    async def get_latest_response_text(self) -> str:
        """
        Extracts text from the latest model response, converting DOM <pre><code> blocks
        into fenced markdown (```lang ... ```) so code blocks are cleanly separated from prose.
        """
        if not self.page:
            return ""
        for sel in RESPONSE_SELECTORS:
            try:
                locator = self.page.locator(sel)
                count = await locator.count()
                if count > 0:
                    text = await locator.last.evaluate(r"""(root) => {
                        const tempNodes = [];
                        const hiddenEls = [];
                        try {
                            root.querySelectorAll('button, .code-block-decoration, .action-buttons, .response-footer').forEach(el => {
                                hiddenEls.push([el, el.style.display]);
                                el.style.display = 'none';
                            });
                            root.querySelectorAll('pre').forEach(pre => {
                                const codeEl = pre.querySelector('code');
                                let lang = '';
                                const block = pre.closest('code-block') || pre.parentElement;
                                if (block) {
                                    const dec = block.querySelector('.code-block-decoration span, .code-block-decoration');
                                    if (dec && dec.textContent) {
                                        lang = dec.textContent.trim().split(/\s+/)[0].toLowerCase();
                                    }
                                }
                                if (!lang && codeEl && codeEl.className) {
                                    const m = codeEl.className.match(/language-([a-zA-Z0-9_-]+)/);
                                    if (m) lang = m[1].toLowerCase();
                                }
                                const codeText = (codeEl ? codeEl.textContent : pre.textContent) || '';
                                const fenceNode = document.createTextNode('\n```' + lang + '\n' + codeText.trim() + '\n```\n');
                                pre.parentNode.insertBefore(fenceNode, pre);
                                hiddenEls.push([pre, pre.style.display]);
                                pre.style.display = 'none';
                                tempNodes.push(fenceNode);
                            });
                            return (root.innerText || '').trim();
                        } finally {
                            tempNodes.forEach(n => n.remove());
                            hiddenEls.forEach(([el, prev]) => { el.style.display = prev; });
                        }
                    }""")
                    text = (text or "").strip()
                    if text and not text.startswith("About Gemini") and not text.startswith("Sign in"):
                        return text
            except Exception:
                pass
        return ""

    async def _response_count(self) -> int:
        for sel in RESPONSE_COUNT_SELECTORS:
            try:
                count = await self.page.locator(sel).count()
                if count > 0:
                    return count
            except Exception:
                pass
        return 0

    async def _is_generating(self) -> bool:
        for sel in STOP_BUTTON_SELECTORS:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _detect_gemini_error(self) -> Optional[str]:
        try:
            body_text = await self.page.locator("body").inner_text(timeout=2000)
        except Exception:
            return None
        for marker in GEMINI_ERROR_MARKERS:
            if marker.lower() in body_text.lower():
                return marker
        return None

    async def capture_debug(self, reason: str) -> Optional[str]:
        """Saves a screenshot + HTML dump of the current page to help diagnose failures."""
        if not self.page:
            return None
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            base = os.path.join(self.debug_dir, f"{stamp}_{reason}")
            await self.page.screenshot(path=f"{base}.png", full_page=True)
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(await self.page.content())
            logger.error(f"Saved debug capture: {base}.png / .html (url={self.page.url})")
            return base
        except Exception as e:
            logger.warning(f"Failed to save debug capture: {e}")
            return None

    async def _read_input_text(self, input_selector: str) -> str:
        try:
            return (await self.page.locator(input_selector).first.inner_text(timeout=2000)).strip()
        except Exception:
            return ""

    async def send_prompt(self, prompt_text: str, timeout: Optional[int] = None, new_chat: bool = False) -> str:
        timeout = timeout or DEFAULT_RESPONSE_TIMEOUT
        async with self._lock:
            if not self.page:
                await self._start_unlocked()

            # 1. Determine conversation context and prepare page
            if new_chat:
                logger.info("New chat requested by OpenWebUI. Navigating to fresh Gemini conversation...")
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(1.5)
            elif not self.page.url.startswith(GEMINI_URL):
                await self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1.0)

            # 2. Dismiss cookie consent & overlay dialogs BEFORE checking auth or touching the input box
            await self._dismiss_overlays()

            prev_response_count = 0 if new_chat else await self._response_count()
            previous_text = "" if new_chat else await self.get_latest_response_text()
            prev_query_count = await self.page.locator(USER_QUERY_SELECTOR).count()

            auth = await self.is_authenticated()
            if not auth:
                await self.capture_debug("not_authenticated")
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
                await self.capture_debug("no_input")
                raise RuntimeError("Could not locate prompt input element on Gemini page.")

            # 3. Focus and insert prompt using native contenteditable command
            input_elem = self.page.locator(input_selector).first
            await input_elem.click(force=True, timeout=5000)
            await asyncio.sleep(0.2)

            # Insert text via execCommand which updates Angular/ProseMirror/Quill models reliably for any prompt size
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

            # Verify the prompt actually landed in the editor; fall back to native keyboard insertion
            if not await self._read_input_text(input_selector):
                logger.warning("Prompt not detected in input after execCommand; retrying with keyboard.insert_text.")
                await input_elem.click(force=True, timeout=5000)
                await self.page.keyboard.insert_text(prompt_text)
                await asyncio.sleep(0.5)
                if not await self._read_input_text(input_selector):
                    await self.capture_debug("prompt_not_inserted")
                    raise RuntimeError("Failed to insert prompt text into Gemini input box.")

            # Ensure no late overlay popped up before clicking send
            await self._dismiss_overlays()

            # 4. Submit: click send button
            send_clicked = False
            for btn_sel in [
                'button[aria-label*="Send message"]',
                'gem-icon-button.send-button button',
                'button.send-button',
                'button[aria-label*="Send"]',
                'button[aria-label*="Submit"]',
                '.send-button-container button',
            ]:
                try:
                    btn = self.page.locator(btn_sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        disabled_attr = await btn.get_attribute("aria-disabled")
                        if disabled_attr == "true":
                            continue
                        try:
                            await btn.click(timeout=3000)
                        except Exception:
                            await btn.evaluate("el => el.click()")
                        send_clicked = True
                        logger.info(f"Clicked send button: {btn_sel}")
                        break
                except Exception:
                    pass

            if not send_clicked:
                logger.info("Send button not clicked directly; pressing Enter.")
                await self.page.keyboard.press("Enter")

            logger.info(
                f"Prompt submitted ({len(prompt_text)} chars, prev responses: {prev_response_count}, "
                f"timeout: {timeout}s). Waiting for new response stream..."
            )

            # 5. Wait for stream to start and stabilize
            start_time = asyncio.get_event_loop().time()
            await asyncio.sleep(2.5)

            # Confirm Gemini registered the submission (a new user-query bubble or input box cleared)
            try:
                query_count = await self.page.locator(USER_QUERY_SELECTOR).count()
                remaining_input = await self._read_input_text(input_selector)
                if query_count <= prev_query_count and len(remaining_input) > 20:
                    logger.warning(
                        f"Prompt still in input box after submit (queries before={prev_query_count}, now={query_count}). "
                        "Dismissing any overlays and retrying submit..."
                    )
                    await self._dismiss_overlays()
                    btn = self.page.locator('button[aria-label*="Send message"], .send-button-container button').first
                    if await btn.count() > 0:
                        await btn.evaluate("el => el.click()")
                    else:
                        await input_elem.focus()
                        await self.page.keyboard.press("Enter")
            except Exception:
                pass

            last_len = -1
            stable_count = 0
            raw_output = ""
            last_progress_log = start_time

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    current_count = await self._response_count()

                    # Multi-turn: a new response element must appear beyond the previous count
                    is_new_bubble = current_count > prev_response_count

                    if is_new_bubble:
                        current_text = await self.get_latest_response_text()
                        if current_text and (prev_response_count == 0 or current_text != previous_text):
                            curr_len = len(current_text)
                            generating = await self._is_generating()
                            if curr_len == last_len and not generating:
                                stable_count += 1
                                if stable_count >= 3:
                                    logger.info(f"Response stream finished (stabilized at {curr_len} chars, response #{current_count}).")
                                    raw_output = current_text
                                    break
                            else:
                                last_len = curr_len
                                stable_count = 0

                    now = asyncio.get_event_loop().time()
                    if now - last_progress_log >= 15:
                        last_progress_log = now
                        logger.info(
                            f"Still waiting... elapsed={int(now - start_time)}s, responses={current_count}, "
                            f"text_len={max(last_len, 0)}, generating={await self._is_generating()}"
                        )
                        err = await self._detect_gemini_error()
                        if err and not is_new_bubble:
                            await self.capture_debug("gemini_error")
                            raise RuntimeError(f"Gemini Web reported an error: '{err}'")
                except RuntimeError:
                    raise
                except Exception as e:
                    logger.debug(f"Error checking text stability: {e}")

                await asyncio.sleep(1.0)

            if not raw_output:
                candidate_text = await self.get_latest_response_text()
                if candidate_text and candidate_text != previous_text:
                    logger.warning("Stream loop finished without stabilization count 3, but found new response text.")
                    raw_output = candidate_text
                else:
                    debug_base = await self.capture_debug("timeout")
                    err = await self._detect_gemini_error()
                    hint = f" Gemini page shows: '{err}'." if err else ""
                    where = f" Debug capture: {debug_base}.png" if debug_base else ""
                    raise TimeoutError(
                        f"Timed out after {timeout}s waiting for Gemini response stream to complete "
                        f"(responses seen: {await self._response_count()}, url: {self.page.url}).{hint}{where}"
                    )

            return raw_output.strip()
