"""HTTP delivery and independent read-back verification."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from .base import PermanentDeliveryError


class MockPMISConnector:
    def __init__(self, url="http://127.0.0.1:8091", timeout=5):
        if urlparse(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("MOCK PMIS requires a loopback receiver")
        self.url = url.rstrip("/")
        self.timeout = timeout

    def request(self, path, payload=None):
        req = Request(self.url + path, data=json.dumps(payload).encode() if payload else None,
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code not in {408, 429}:
                raise PermanentDeliveryError(f"Receiver mapping/version/contract error ({exc.code})") from exc
            raise

    def deliver(self, payload):
        receipt = self.request("/updates", payload)
        path = "/activities/" + "/".join(quote(str(payload[k]), safe="") for k in
            ("external_project_id", "source_schedule_version_id", "external_activity_id"))
        current = self.request(path)
        if current["state_revision"] < payload["state_revision"]:
            raise RuntimeError("Read-back revision behind delivered snapshot")
        if current["state_revision"] == payload["state_revision"] and current["state"] != payload["state"]:
            raise PermanentDeliveryError("Read-back state disagrees at same revision")
        return {**receipt, "read_back_revision": current["state_revision"], "verified": True}
