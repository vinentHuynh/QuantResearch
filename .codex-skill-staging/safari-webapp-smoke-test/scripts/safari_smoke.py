#!/usr/bin/env python3
"""Capture Safari WebDriver smoke-test evidence for a running localhost app."""

from __future__ import annotations

import argparse
import base64
import json
import math
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


STATE_SCRIPT = """
const expectedText = arguments[0] || "";
const bodyText = document.body ? document.body.innerText : "";
const brokenImages = Array.from(document.images)
  .filter((image) => image.complete && image.naturalWidth === 0)
  .map((image) => image.currentSrc || image.src);
return {
  title: document.title,
  url: location.href,
  readyState: document.readyState,
  bodyPresent: Boolean(document.body),
  bodyTextLength: bodyText.length,
  hasExpectedText: !expectedText || bodyText.includes(expectedText),
  headings: Array.from(document.querySelectorAll("h1, h2"))
    .map((element) => element.innerText.trim())
    .filter(Boolean),
  viteErrorOverlay: Boolean(document.querySelector("vite-error-overlay")),
  brokenImages,
  viewport: [window.innerWidth, window.innerHeight],
  bodyClientWidth: document.body ? document.body.clientWidth : 0,
  bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
  bodyHorizontalOverflow: document.body
    ? document.body.scrollWidth > document.body.clientWidth
    : false
};
"""

EXPECTATION_SCRIPT = """
const expected = arguments[0] || {};
const bodyText = document.body ? document.body.innerText : "";
const element = expected.css ? document.querySelector(expected.css) : null;
const observedText = element ? (element.innerText || element.textContent || "").trim() : null;
const observedValue = element && "value" in element ? element.value : null;
return {
  bodyTextMatched: !expected.body_text || bodyText.includes(expected.body_text),
  selectorFound: !expected.css || Boolean(element),
  textMatched: !("text" in expected) || observedText === expected.text,
  valueMatched: !("value" in expected) || observedValue === expected.value,
  observedText,
  observedValue,
  currentUrl: location.href
};
"""


class SmokeError(RuntimeError):
    """Operational Safari/WebDriver failure."""


class WebDriverClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                detail = json.loads(raw.decode("utf-8"))
                value = detail.get("value", detail)
                message = value.get("message", value) if isinstance(value, dict) else value
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = raw.decode("utf-8", errors="replace")
            raise SmokeError(f"WebDriver HTTP {error.code}: {message}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SmokeError(f"WebDriver request failed: {error}") from error

        if not raw:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SmokeError("WebDriver returned a non-JSON response") from error
        value = result.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise SmokeError(f"{value['error']}: {value.get('message', '')}")
        return result


def parse_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", maxsplit=1)
        width, height = int(width_text), int(height_text)
    except (ValueError, AttributeError) as error:
        raise argparse.ArgumentTypeError("size must use WIDTHxHEIGHT") from error
    if width < 200 or height < 200:
        raise argparse.ArgumentTypeError("width and height must each be at least 200")
    return width, height


def bounded_float(value: str, *, label: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be a number") from error
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label} must be between {minimum:g} and {maximum:g}"
        )
    return parsed


def parse_timeout(value: str) -> float:
    return bounded_float(value, label="timeout", minimum=0.5, maximum=300)


def parse_settle(value: str) -> float:
    return bounded_float(value, label="settle", minimum=0, maximum=30)


def parse_driver_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("driver port must be an integer") from error
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("driver port must be between 0 and 65535")
    return port


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def local_url_error(value: str) -> str | None:
    if value != value.strip() or "\\" in value or any(ord(char) < 32 for char in value):
        return "URL contains whitespace, control characters, or a backslash"
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        return f"invalid URL authority: {error}"
    if parsed.scheme not in {"http", "https"}:
        return "URL must use http or https"
    if not parsed.netloc or parsed.hostname is None:
        return "URL must include a host"
    if parsed.username is not None or parsed.password is not None:
        return "URL user information is not allowed"
    if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        return "this helper accepts loopback URLs only"
    return None


def validate_local_url(value: str) -> str:
    error = local_url_error(value)
    if error:
        raise argparse.ArgumentTypeError(error)
    return value


def require_local_runtime_url(value: Any) -> None:
    if not isinstance(value, str):
        raise SmokeError("browser did not return its current URL")
    error = local_url_error(value)
    if error:
        raise SmokeError(f"browser left loopback URL boundary: {value!r} ({error})")


def value_of(response: dict[str, Any]) -> Any:
    return response.get("value")


def activate_safari(app_name: str) -> dict[str, Any]:
    try:
        activated = subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"attempted": True, "succeeded": False, "error": "activation timed out"}
    return {
        "attempted": True,
        "succeeded": activated.returncode == 0,
        "error": activated.stderr.strip() or None,
    }


def wait_for_driver(
    client: WebDriverClient, process: subprocess.Popen[str], timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeError(f"safaridriver exited with status {process.returncode}")
        try:
            status = value_of(client.request("/status", timeout=1))
            if isinstance(status, dict) and status.get("ready") is True:
                return
        except SmokeError:
            pass
        time.sleep(0.1)
    raise SmokeError("timed out waiting for safaridriver")


def inspect_state(
    client: WebDriverClient, session_id: str, expected_text: str | None
) -> dict[str, Any]:
    response = client.request(
        f"/session/{session_id}/execute/sync",
        method="POST",
        payload={"script": STATE_SCRIPT, "args": [expected_text or ""]},
    )
    value = value_of(response)
    if not isinstance(value, dict):
        raise SmokeError("WebDriver DOM inspection returned an unexpected value")
    return value


def wait_for_page(
    client: WebDriverClient,
    session_id: str,
    expected_text: str | None,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_state = inspect_state(client, session_id, expected_text)
        require_local_runtime_url(last_state.get("url"))
        if (
            last_state.get("readyState") == "complete"
            and last_state.get("bodyPresent") is True
            and last_state.get("hasExpectedText")
        ):
            return last_state
        time.sleep(0.2)
    detail = "expected text did not appear" if expected_text else "page did not finish rendering"
    raise SmokeError(f"{detail}; last state: {last_state}")


def load_interaction_plan(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeError(f"could not read interaction plan {path}: {error}") from error
    if not isinstance(raw, list) or not raw:
        raise SmokeError("interaction plan must be a non-empty JSON array")

    plan: list[dict[str, Any]] = []
    allowed_expectations = {"body_text", "css", "text", "value"}
    allowed_step_keys = {"name", "using", "value", "expect", "timeout"}
    for index, candidate in enumerate(raw, start=1):
        if not isinstance(candidate, dict):
            raise SmokeError(f"interaction step {index} must be an object")
        unknown_step_keys = set(candidate) - allowed_step_keys
        if unknown_step_keys:
            raise SmokeError(
                f"interaction step {index} has unsupported keys: {sorted(unknown_step_keys)}"
            )
        name = candidate.get("name") or f"step {index}"
        using = candidate.get("using", "css selector")
        locator = candidate.get("value")
        expectation = candidate.get("expect")
        timeout = candidate.get("timeout", 8.0)
        if using not in {"css selector", "xpath"}:
            raise SmokeError(f"{name}: using must be 'css selector' or 'xpath'")
        if not isinstance(locator, str) or not locator:
            raise SmokeError(f"{name}: value must be a non-empty locator")
        if not isinstance(expectation, dict) or not expectation:
            raise SmokeError(f"{name}: expect must be a non-empty object")
        unknown = set(expectation) - allowed_expectations
        if unknown:
            raise SmokeError(f"{name}: unsupported expectation keys: {sorted(unknown)}")
        if any(
            not isinstance(expectation[key], str) or not expectation[key]
            for key in expectation
        ):
            raise SmokeError(f"{name}: expectation values must be non-empty strings")
        if ("text" in expectation or "value" in expectation) and not expectation.get("css"):
            raise SmokeError(f"{name}: text/value expectations require expect.css")
        if not isinstance(timeout, (int, float)) or not 0.1 <= float(timeout) <= 60:
            raise SmokeError(f"{name}: timeout must be between 0.1 and 60 seconds")
        plan.append(
            {
                "name": str(name),
                "using": using,
                "value": locator,
                "expect": expectation,
                "timeout": float(timeout),
            }
        )
    return plan


def expectation_passed(state: dict[str, Any]) -> bool:
    return all(
        state.get(key) is True
        for key in ("bodyTextMatched", "selectorFound", "textMatched", "valueMatched")
    )


def evaluate_expectation(
    client: WebDriverClient,
    session_id: str,
    expectation: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = client.request(
        f"/session/{session_id}/execute/sync",
        method="POST",
        payload={"script": EXPECTATION_SCRIPT, "args": [expectation]},
        timeout=timeout,
    )
    observed = value_of(response)
    if not isinstance(observed, dict):
        raise SmokeError("interaction expectation returned an unexpected value")
    require_local_runtime_url(observed.get("currentUrl"))
    return observed


def get_window_handles(
    client: WebDriverClient, session_id: str, timeout: float
) -> set[str]:
    handles = value_of(
        client.request(f"/session/{session_id}/window/handles", timeout=timeout)
    )
    if not isinstance(handles, list) or not all(isinstance(item, str) for item in handles):
        raise SmokeError("WebDriver returned invalid window handles")
    return set(handles)


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise SmokeError("interaction step timed out")
    return max(0.1, value)


def run_interaction_plan(
    client: WebDriverClient,
    session_id: str,
    plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for step in plan:
        deadline = time.monotonic() + step["timeout"]
        initial_handles = get_window_handles(client, session_id, remaining(deadline))
        before = evaluate_expectation(
            client, session_id, step["expect"], remaining(deadline)
        )
        if expectation_passed(before):
            raise SmokeError(
                f"{step['name']}: postcondition was already true before the click; "
                "choose an expectation that proves a state transition"
            )
        element_id: str | None = None
        last_locator_error: str | None = None
        while time.monotonic() < deadline and element_id is None:
            try:
                found = value_of(
                    client.request(
                        f"/session/{session_id}/element",
                        method="POST",
                        payload={"using": step["using"], "value": step["value"]},
                        timeout=remaining(deadline),
                    )
                )
                if isinstance(found, dict) and found:
                    candidate = next(iter(found.values()))
                    if isinstance(candidate, str):
                        element_id = candidate
            except SmokeError as error:
                last_locator_error = str(error)
                normalized = last_locator_error.lower()
                if not any(
                    marker in normalized
                    for marker in ("no such element", "could not be located", "not found")
                ):
                    raise
            if element_id is None:
                time.sleep(0.1)
        if element_id is None:
            raise SmokeError(
                f"{step['name']}: locator was not found"
                + (f" ({last_locator_error})" if last_locator_error else "")
            )

        client.request(
            f"/session/{session_id}/element/{element_id}/click",
            method="POST",
            payload={},
            timeout=remaining(deadline),
        )
        after_click_handles = get_window_handles(client, session_id, remaining(deadline))
        if after_click_handles != initial_handles:
            raise SmokeError(
                f"{step['name']}: click changed browser windows; interaction plans must "
                "remain in the existing loopback window"
            )
        last_expectation: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            observed = evaluate_expectation(
                client, session_id, step["expect"], remaining(deadline)
            )
            last_expectation = observed
            if expectation_passed(observed):
                break
            time.sleep(0.1)
        if last_expectation is None or not expectation_passed(last_expectation):
            raise SmokeError(
                f"{step['name']}: expectation timed out; observed {last_expectation}. "
                "Ensure Safari remains foregrounded for trusted clicks."
            )
        final_handles = get_window_handles(client, session_id, remaining(deadline))
        if final_handles != initial_handles:
            raise SmokeError(
                f"{step['name']}: browser window set changed during interaction"
            )
        results.append(
            {
                "name": step["name"],
                "using": step["using"],
                "value": step["value"],
                "expect": step["expect"],
                "before": before,
                "observed": last_expectation,
                "passed": True,
            }
        )
    return results


def capture_viewport(
    client: WebDriverClient,
    session_id: str,
    label: str,
    size: tuple[int, int],
    expected_text: str | None,
    output_dir: Path,
    settle_seconds: float,
    overwrite: bool,
) -> dict[str, Any]:
    width, height = size
    client.request(
        f"/session/{session_id}/window/rect",
        method="POST",
        payload={"width": width, "height": height, "x": 20, "y": 20},
    )
    time.sleep(settle_seconds)
    state = inspect_state(client, session_id, expected_text)
    require_local_runtime_url(state.get("url"))
    screenshot = value_of(client.request(f"/session/{session_id}/screenshot"))
    if not isinstance(screenshot, str):
        raise SmokeError("WebDriver screenshot response was not base64 text")
    image_path = output_dir / f"{label}.png"
    if image_path.exists() and not overwrite:
        raise SmokeError(
            f"refusing to overwrite {image_path}; choose a new output directory or pass --overwrite"
        )
    try:
        image_path.write_bytes(base64.b64decode(screenshot, validate=True))
    except (ValueError, OSError) as error:
        raise SmokeError(f"could not write screenshot {image_path}: {error}") from error
    state["requestedWindowSize"] = [width, height]
    state["screenshot"] = str(image_path)
    return state


def stop_driver_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test a running localhost app in Safari and capture screenshots.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("url", type=validate_local_url, help="running localhost URL")
    parser.add_argument("--expected-title", help="exact document title to require")
    parser.add_argument("--wait-for-text", help="rendered body text to wait for")
    parser.add_argument(
        "--desktop-window",
        "--desktop",
        dest="desktop",
        type=parse_size,
        default=(1440, 1000),
        help="outer Safari window size WIDTHxHEIGHT for the desktop check",
    )
    parser.add_argument(
        "--mobile-window",
        "--mobile",
        dest="mobile",
        type=parse_size,
        default=(390, 844),
        help="outer Safari window size WIDTHxHEIGHT for the phone-width check",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="screenshot directory; defaults to a unique temp directory"
    )
    parser.add_argument("--interaction-plan", type=Path, help="reviewed native-click plan JSON")
    parser.add_argument(
        "--timeout", type=parse_timeout, default=30.0, help="startup and page-render timeout"
    )
    parser.add_argument(
        "--settle", type=parse_settle, default=0.8, help="seconds to settle after window resizing"
    )
    parser.add_argument(
        "--driver-port", type=parse_driver_port, default=0, help="SafariDriver port; 0 chooses one"
    )
    parser.add_argument(
        "--safaridriver", default="/usr/bin/safaridriver", help="SafariDriver executable"
    )
    parser.add_argument(
        "--safari-app",
        choices=("Safari", "Safari Technology Preview"),
        default="Safari",
        help="browser application to foreground",
    )
    parser.add_argument(
        "--no-activate", action="store_true", help="do not attempt to foreground Safari"
    )
    parser.add_argument(
        "--fail-on-overflow", action="store_true", help="fail on body-level horizontal overflow"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace existing desktop/mobile screenshots"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        interaction_plan = (
            load_interaction_plan(args.interaction_plan.resolve())
            if args.interaction_plan
            else []
        )
    except SmokeError as error:
        print(json.dumps({"passed": False, "error": str(error)}), file=sys.stderr)
        return 2
    driver_path = Path(args.safaridriver)
    if not driver_path.is_file():
        print(json.dumps({"passed": False, "error": f"missing {driver_path}"}), file=sys.stderr)
        return 2

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="safari-webapp-smoke-"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    port = args.driver_port or choose_port()
    client = WebDriverClient(f"http://127.0.0.1:{port}")
    session_id: str | None = None
    driver_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    process: subprocess.Popen[str] | None = None
    cleanup_errors: list[str] = []

    try:
        process = subprocess.Popen(
            [str(driver_path), "-p", str(port)],
            stdout=driver_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_driver(client, process, args.timeout)
        created = client.request(
            "/session",
            method="POST",
            payload={"capabilities": {"alwaysMatch": {"browserName": "Safari"}}},
            timeout=args.timeout,
        )
        created_value = value_of(created)
        if not isinstance(created_value, dict) or not created_value.get("sessionId"):
            raise SmokeError("WebDriver did not return a Safari session ID")
        session_id = str(created_value["sessionId"])

        activation: dict[str, Any]
        if args.no_activate:
            activation = {"attempted": False}
        else:
            activation = activate_safari(args.safari_app)
        if interaction_plan and activation.get("succeeded") is not True:
            raise SmokeError(
                "Safari activation must succeed before native interaction steps"
            )

        client.request(
            f"/session/{session_id}/url",
            method="POST",
            payload={"url": args.url},
            timeout=args.timeout,
        )
        initial = wait_for_page(
            client, session_id, args.wait_for_text, timeout=args.timeout
        )
        desktop = capture_viewport(
            client,
            session_id,
            "desktop",
            args.desktop,
            args.wait_for_text,
            output_dir,
            args.settle,
            args.overwrite,
        )
        mobile = capture_viewport(
            client,
            session_id,
            "mobile",
            args.mobile,
            args.wait_for_text,
            output_dir,
            args.settle,
            args.overwrite,
        )

        interactions: list[dict[str, Any]] = []
        if interaction_plan:
            width, height = args.desktop
            client.request(
                f"/session/{session_id}/window/rect",
                method="POST",
                payload={"width": width, "height": height, "x": 20, "y": 20},
            )
            if not args.no_activate:
                interaction_activation = activate_safari(args.safari_app)
                if interaction_activation.get("succeeded") is not True:
                    raise SmokeError(
                        "Safari could not be foregrounded for native interaction steps"
                    )
            time.sleep(args.settle)
            interactions = run_interaction_plan(client, session_id, interaction_plan)

        failures: list[str] = []
        if args.expected_title and initial.get("title") != args.expected_title:
            failures.append(
                f"title was {initial.get('title')!r}, expected {args.expected_title!r}"
            )
        for label, state in (("desktop", desktop), ("mobile", mobile)):
            if state.get("readyState") != "complete" or state.get("bodyTextLength", 0) <= 0:
                failures.append(f"{label}: rendered document is not complete or is empty")
            if args.wait_for_text and not state.get("hasExpectedText"):
                failures.append(f"{label}: expected text is missing")
            if args.expected_title and state.get("title") != args.expected_title:
                failures.append(f"{label}: document title changed unexpectedly")
            if state.get("viteErrorOverlay"):
                failures.append(f"{label}: Vite error overlay is present")
            if state.get("brokenImages"):
                failures.append(f"{label}: broken images: {state['brokenImages']}")
            if args.fail_on_overflow and state.get("bodyHorizontalOverflow"):
                failures.append(f"{label}: body has horizontal overflow")

        client.request(f"/session/{session_id}", method="DELETE", timeout=5)
        session_id = None
        stop_driver_process(process)
        process = None

        summary = {
            "passed": not failures,
            "url": args.url,
            "sessionCapabilities": created_value.get("capabilities", {}),
            "activation": activation,
            "outputDirectory": str(output_dir),
            "initial": initial,
            "viewports": {"desktop": desktop, "mobile": mobile},
            "interactions": interactions,
            "cleanup": {"sessionDeleted": True, "driverStopped": True},
            "failures": failures,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if not failures else 1
    except (SmokeError, OSError, subprocess.SubprocessError) as error:
        driver_log.seek(0)
        log_tail = driver_log.read()[-2000:].strip()
        print(
            json.dumps(
                {
                    "passed": False,
                    "error": str(error),
                    "driverLog": log_tail or None,
                    "outputDirectory": str(output_dir),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if session_id:
            try:
                client.request(f"/session/{session_id}", method="DELETE", timeout=5)
            except SmokeError as error:
                cleanup_errors.append(str(error))
        if process:
            try:
                stop_driver_process(process)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(str(error))
        driver_log.close()
        if cleanup_errors:
            print(json.dumps({"cleanupErrors": cleanup_errors}), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
