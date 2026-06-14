import importlib.util
import os
import unittest
from pathlib import Path
from unittest import SkipTest

import aiohttp
from aiohttp import ContentTypeError


MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "pvpc_energy" / "ufd.py"
SPEC = importlib.util.spec_from_file_location("ufd", MODULE_PATH)
ufd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ufd)


class FakeResponse:
    def __init__(self, *, status=200, url="https://api.ufd.es/ufd/v1.0/login", text="", payload=None, content_type="text/html; charset=utf-8"):
        self.status = status
        self.url = url
        self._text = text
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    async def json(self):
        if self._payload is not None:
            return self._payload
        raise ContentTypeError(None, (), message="unexpected mimetype")

    async def text(self):
        return self._text


class UFDResponseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ufd.UFD._blocked_until = None
        ufd.UFD._block_attempts = 0
        ufd.UFD._last_block_reason = None
        ufd.UFD._user_agent = None
        ufd.UFD._user_agent_requests = 0

    async def test_captcha_html_response_returns_none(self):
        response = FakeResponse(
            url="https://validate.perfdrive.com/?ssa=test",
            text="Captcha Page Please solve this CAPTCHA to request unblock to the website",
        )

        with self.assertLogs("ufd", level="WARNING") as logs:
            result = await ufd.UFD.checkResponse(response)

        self.assertIsNone(result)
        self.assertTrue(any("pagina de bloqueo/CAPTCHA" in line for line in logs.output))
        self.assertTrue(ufd.UFD.isBackoffActive())

    async def test_json_response_is_returned(self):
        payload = {"accessToken": "token", "user": {"userId": "1", "documentNumber": "12345678Z"}}
        response = FakeResponse(payload=payload, content_type="application/json")

        result = await ufd.UFD.checkResponse(response)

        self.assertEqual(result, payload)

    def test_user_agent_is_reused_until_request_limit(self):
        ufd.UFD.USER_AGENT_MAX_REQUESTS = 3
        try:
            first = ufd.UFD.getUserAgent()
            self.assertEqual(ufd.UFD.getUserAgent(), first)
            self.assertEqual(ufd.UFD.getUserAgent(), first)
            ufd.UFD.getUserAgent()
            self.assertEqual(ufd.UFD._user_agent_requests, 1)
        finally:
            ufd.UFD.USER_AGENT_MAX_REQUESTS = 12


class UFDIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Tests de integración que verifican los endpoints reales de la API de UFD."""

    SKIP_INTEGRATION = "SKIP_INTEGRATION" in os.environ

    def setUp(self):
        if self.SKIP_INTEGRATION:
            raise SkipTest("SKIP_INTEGRATION env var set — skipping integration tests")
        ufd.UFD._blocked_until = None
        ufd.UFD._block_attempts = 0
        ufd.UFD._last_block_reason = None

    async def _http_get(self, url, headers=None):
        if headers is None:
            headers = {
                "accept": "application/json",
                "user-agent": ufd.UFD.USER_AGENTS[0],
            }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                return resp.status, await resp.text()

    async def _http_post(self, url, json=None, headers=None):
        if headers is None:
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "user-agent": ufd.UFD.USER_AGENTS[0],
            }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=json, ssl=False) as resp:
                return resp.status, await resp.text()

    async def test_login_endpoint_responds(self):
        """El nuevo endpoint de login en mapi.ufd.es debe responder (no 404)."""
        status, body = await self._http_post(ufd.UFD.login_url, json={})
        self.assertNotEqual(status, 404, f"login_url devuelve 404: {ufd.UFD.login_url}")
        print(f"  login_url → {status}")

    async def test_supplypoints_endpoint_responds(self):
        """El endpoint de supplypoints debe responder (401 sin token, no 404)."""
        url = ufd.UFD.supplypoints_url.format(nif="00000000T")
        status, body = await self._http_get(url)
        self.assertNotEqual(status, 404, f"supplypoints_url devuelve 404: {url}")
        print(f"  supplypoints_url → {status}")

    async def test_billing_periods_endpoint_responds(self):
        """El endpoint de billingPeriods debe responder (401 sin token, no 404)."""
        url = ufd.UFD.billingPeriods_url.format(
            cups="ES0000000000000000AA0F",
            start_date="01%2F01%2F2025",
            end_date="01%2F02%2F2025",
        )
        status, body = await self._http_get(url)
        self.assertNotEqual(status, 404, f"billingPeriods_url devuelve 404: {url}")
        print(f"  billingPeriods_url → {status}")

    async def test_consumptions_endpoint_responds(self):
        """El endpoint de consumptions debe responder (401 sin token, no 404)."""
        url = ufd.UFD.consumptions_url.format(
            nif="00000000T",
            cups="ES0000000000000000AA0F",
            start_date="01%2F01%2F2025",
            end_date="01%2F02%2F2025",
        )
        status, body = await self._http_get(url)
        self.assertNotEqual(status, 404, f"consumptions_url devuelve 404: {url}")
        print(f"  consumptions_url → {status}")

    async def test_login_endpoint_accepts_post(self):
        """El endpoint de login acepta POST y devuelve JSON (aunque las credenciales sean inválidas)."""
        status, body = await self._http_post(ufd.UFD.login_url, json={"user": "", "password": ""})
        self.assertNotEqual(status, 404, f"login_url devuelve 404: {ufd.UFD.login_url}")
        self.assertNotEqual(status, 405, f"login_url no acepta POST: {status}")
        print(f"  login POST ({status}) → {body[:100]}")

    async def test_all_api_urls_use_new_base(self):
        """Todas las URLs deben apuntar al nuevo dominio mapi.ufd.es."""
        for attr in ("login_url", "supplypoints_url", "billingPeriods_url", "consumptions_url"):
            url = getattr(ufd.UFD, attr)
            self.assertTrue(url.startswith("https://mapi.ufd.es/"),
                            f"{attr} no usa mapi.ufd.es: {url}")
        print("  todas las URLs usan mapi.ufd.es → OK")


if __name__ == "__main__":
    unittest.main()
