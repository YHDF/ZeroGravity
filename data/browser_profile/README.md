# Browser Profile Directory (`/data/browser_profile`)

This directory represents the **Chromium User Data Directory** used by Playwright in the `gemini-bridge` service.

## 🎯 What is it good for?

In Playwright, ZeroGravity launches Chromium with a persistent browser context:
```python
self.context = await self.playwright.chromium.launch_persistent_context(
    user_data_dir=profile_dir,
    headless=is_headless,
    ...
)
```

By persisting this directory, the browser saves:
1. **Google Account Authentication**: Active session cookies (`SID`, `HSID`, `SSID`, `__Secure-1PSID`) so you only need to authenticate once. Subsequent container restarts remain logged in.
2. **Cookie & Consent Decisions**: Google EU cookie banner choices (`accept` / `reject`) so dialogues do not block page automation.
3. **Gemini Web Local Storage**: Client-side app state, conversation cache, and theme settings.
4. **V8 Code Cache**: Compiled JavaScript bytecode for Gemini Web, speeding up browser startup.

---

## 📂 Anatomy of a Live Profile

At runtime, Chromium automatically creates and maintains the following structure:

```text
browser_profile/
├── Preferences                     # JSON file with browser configuration & flags
├── Default/                        # Default user profile
│   ├── Cookies                     # SQLite 3 database with persistent session cookies
│   ├── Cookies-journal             # SQLite write-ahead rollback journal
│   ├── Local Storage/
│   │   └── leveldb/                # LevelDB storing localStorage keys for gemini.google.com
│   ├── Session Storage/            # Tab-scoped session storage
│   ├── Cache/                      # HTTP resource cache
│   ├── Code Cache/
│   │   ├── js/                     # V8 bytecode cache
│   │   └── wasm/                   # WebAssembly cache
│   ├── Network Action Predictor    # SQLite database for predictive network connections
│   └── Shared Storage/             # Chromium shared storage API
└── gemini_debug.png                # Optional Playwright debug capture on error/timeout
```

---

## 🔒 Security Notice

> [!WARNING]
> Live profile directories contain **real authentication session cookies** and are therefore **strictly ignored by git** in `.gitignore`. Never commit or publish live `Cookies` SQLite databases or `Local Storage` files.

---

## ⚙️ Docker vs Native Bridge Mapping

- **In Docker (`docker-compose.yml`)**:
  Mounted from host path `~/.zerogravity-profile` to `/data/browser_profile`:
  ```yaml
  volumes:
    - ~/.zerogravity-profile:/data/browser_profile
  ```
- **Native Host Bridge (`services/browser_bridge/run_local.ps1`)**:
  Uses `$HOME/.zerogravity-profile` directly on Windows, allowing host browsers (Brave, Chrome, Edge) to share the same authenticated profile.

