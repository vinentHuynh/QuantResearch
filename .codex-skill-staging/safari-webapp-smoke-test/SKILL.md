---
name: safari-webapp-smoke-test
description: Run and visually test localhost web apps with Safari WebDriver on macOS, including responsive screenshots and non-destructive UI interactions. Use when asked to start or connect to a local dev server and inspect or exercise the rendered page; do not use for API-only, unit-test-only, or production-site testing.
---

# Safari Web App Smoke Test

Exercise the real rendered app and return evidence while keeping application data unchanged.

## Workflow

1. Read repository instructions and inspect the requested dev script before running it. Preserve the user's command, URL, and ports. Check whether required dependencies already exist; do not install browser tooling when Safari WebDriver is available.
2. Probe the requested URL first. Reuse an already-running healthy app and do not claim or stop its process. Otherwise, start the dev stack in a persistent terminal session and wait for every service to become ready. If localhost binding fails with `EPERM`, retry through the normal escalation flow. Probe the exact advertised host: Vite may bind `localhost`/`::1` while an API binds `127.0.0.1`.
3. Verify the frontend document, transformed/static assets, direct API health where applicable, and frontend-to-API proxy before browser automation. Treat HTTP success as a transport check, not proof that the UI rendered.
4. Inspect the frontend source to identify stable selectors and classify controls before clicking:
   - Safe only after inspection: controls proven to stay in the same loopback window and change only ephemeral page state, plus idempotent reads whose implementation has no logout, tracking mutation, cache invalidation, or other side effect. A `GET` method alone is not proof of safety.
   - Do not exercise without explicit authorization: save, submit, run, import, approve, acknowledge, resolve, POST/PUT/PATCH/DELETE actions, downloads, or controls whose effects are unclear.
5. Run the helper for a baseline rendered-DOM check and responsive screenshots. It starts and cleans up its own SafariDriver process and WebDriver session; the app server must already be running. Resolve `<skill-directory>` from the absolute path of this loaded `SKILL.md`—never invoke a same-named script from the target repository:

   ```bash
   python3 <skill-directory>/scripts/safari_smoke.py http://localhost:5173 \
     --expected-title "Expected title" \
     --wait-for-text "Expected heading"
   ```

   With no output directory, the helper creates a unique temporary directory. Read its `--help` for optional window sizes, explicit output/overwrite behavior, interaction plans, and stricter overflow handling. It rejects non-loopback destinations and fails if a localhost page redirects outside loopback. Running it launches and foregrounds Safari, so request the required GUI/local-port approval immediately before execution.
6. For app-specific interactions, write a reviewed JSON plan to a unique temporary path outside the target repository, then pass `--interaction-plan <absolute-path>`. Each step performs a native WebDriver click and must include a postcondition that is false before the click and true afterward. Use `css selector` or `xpath` locators:

   ```json
   [
     {
       "name": "Open health",
       "using": "css selector",
       "value": ".navTabs > button:nth-child(2)",
       "expect": {
         "body_text": "Strategy health",
         "css": ".navTabs > button.active",
         "text": "HEALTH"
       }
     }
   ]
   ```

   Expectations support `body_text`, plus `css` with optional exact `text` and/or form-control `value`. Inspect source and network behavior before every click; exclude links or handlers that open windows, leave loopback, write browser storage, or mutate application data. Include restoration steps for ephemeral selections when practical, but do not rely on them for rollback: the helper stops on the first failure. Disclose any state that may remain changed. Remove the temporary plan after the run. When navigation scrolls horizontally, verify an initially off-screen item can be brought into view and activated.
7. Inspect screenshots from a representative desktop-sized Safari window (default `1440x1000`) and phone-width Safari window (default `390x844`). The helper records the actual CSS viewport; this is responsive desktop-Safari testing, not iOS/mobile-browser emulation. Check content visibility, clipping, unintended page-level overflow, responsive navigation, error overlays, and broken images. Distinguish scrollable component overflow from body-level layout overflow.
8. Review server logs after browser activity. Confirm expected browser/API requests succeeded and note errors. Run repository lint or tests only when useful to the requested scope.
9. Report application-state warnings separately from test failures. For example, incomplete configuration or empty research data can be a valid rendered state rather than a UI defect.

## Safari Preconditions

- Require macOS Safari and `/usr/bin/safaridriver`.
- If session creation says remote automation is disabled, ask the user to enable **Safari Settings → Developer → Allow remote automation**, then retry. Do not change Safari preferences on the user's behalf.
- `Allow JavaScript from Apple Events` and macOS Accessibility access are not required by the helper.
- A WebDriver screenshot is preferable to physical-display capture because it works without Screen Recording permission.
- The helper attempts to foreground the app named by `--safari-app` (default `Safari`). When interactions are requested, activation must succeed. Pass the matching app name when using another Safari build.

## Cleanup and Handoff

Use cleanup paths even after failures: delete the WebDriver session, stop the SafariDriver process, remove temporary interaction plans, and stop only the dev-server processes started for the test. Do not close unrelated Safari windows or leave the app running unless the user asks. State whether files or persistent application data changed, and link the captured screenshots when useful.
