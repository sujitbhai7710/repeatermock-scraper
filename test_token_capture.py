"""Unit test for extract_rotated_tokens / get_set_cookie_headers (no network)."""
import sys, json
sys.path.insert(0, ".")
from src.scraper import extract_rotated_tokens, get_set_cookie_headers


class FakeResp:
    """Mimics Playwright APIResponse: headers_array() + merged .headers dict."""
    def __init__(self, set_cookies, body):
        self._sc = set_cookies
        self.headers = {"set-cookie": "\n".join(set_cookies)}
        self._body = body
    def headers_array(self):
        return [{"name": "set-cookie", "value": v} for v in self._sc] + \
               [{"name": "content-type", "value": "application/json"}]
    def text(self):
        return self._body


# Case 1: multiple Set-Cookie headers (the real /auth/refresh shape)
resp = FakeResp(
    [
        "accessToken=newAT123; Path=/; HttpOnly; Secure; SameSite=Lax",
        "refreshToken=newRT456; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000",
        "totpVerified=1; Path=/; Secure",
    ],
    '{"success":true}',
)
tokens, sources = extract_rotated_tokens(resp, resp.text())
assert tokens["accessToken"] == "newAT123", tokens
assert tokens["refreshToken"] == "newRT456", tokens
assert tokens["totpVerified"] == "1", tokens
assert len(sources) == 3, sources
print("PASS case 1: multiple Set-Cookie headers →", sorted(tokens))

# Case 2: tokens only in the JSON body (fallback path)
resp2 = FakeResp([], '{"success":true,"data":{"user":{"accessToken":"bodyAT","refreshToken":"bodyRT"}}}')
tokens2, sources2 = extract_rotated_tokens(resp2, resp2.text())
assert tokens2 == {"accessToken": "bodyAT", "refreshToken": "bodyRT"}, tokens2
print("PASS case 2: body fallback →", sorted(tokens2))

# Case 3: merged dict-style header (comma-joined), no headers_array available
class MergedResp:
    headers = {"set-cookie": "accessToken=mAT1; Path=/; Expires=Wed, 01 Oct 2026 05:30:56 GMT, refreshToken=mRT2; Path=/; Expires=Wed, 01 Oct 2026 05:30:56 GMT"}
    def headers_array(self):
        raise RuntimeError("not available")
resp3 = MergedResp()
vals = get_set_cookie_headers(resp3)
tokens3, _ = extract_rotated_tokens(resp3, "{}")
assert tokens3.get("accessToken") == "mAT1", tokens3
assert tokens3.get("refreshToken") == "mRT2", tokens3
print("PASS case 3: merged header fallback →", sorted(tokens3))

# Case 4: deleted/empty cookie values must be ignored
resp4 = FakeResp(["refreshToken=; Path=/; Max-Age=0", "accessToken=kept; Path=/"], "{}")
tokens4, _ = extract_rotated_tokens(resp4, "{}")
assert "refreshToken" not in tokens4 and tokens4["accessToken"] == "kept", tokens4
print("PASS case 4: deleted values ignored →", sorted(tokens4))

# Case 5: totally broken response → no tokens, no crash
resp5 = FakeResp([], "not json at all")
tokens5, sources5 = extract_rotated_tokens(resp5, resp5.text())
assert tokens5 == {}
print("PASS case 5: garbage response → no crash")

print("\nALL 5 TESTS PASSED")
