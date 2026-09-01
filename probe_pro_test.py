"""Probe the paid test 'CT 28: Algebraic Identities - 01' with the given cookies.
Reports which stages (questions / answers+solutions / analysis) are reachable."""
import json
import urllib.error
import urllib.request

API = "https://api.repeatermock.com"
SITE = "https://repeatermock.com"
VARIANT = "tb-pro"
SLUG = "ssc-cgl"
TEST_ID = "6a0f3cc4076c0c0843115e2f"   # CT 28: Algebraic Identities - 01

COOKIES = [
    {"name": "accessToken", "value": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2YTk1ZDZlNjljNDk1OGE2NzEyNzkzMTciLCJlbWFpbCI6ImRpYmFrYXJzZHNlbnNlQGdtYWlsLmNvbSIsImlhdCI6MTc4ODI5MDIwMSwiZXhwIjoxNzg4MjkxMTAxfQ.nnn4SsHPgWL9dHRVPumW96hYJKaBdH2U49JXv4kMxMA"},
    {"name": "refreshToken", "value": "a416764efa4b322966408b4f6eca48c2985d859459dc686a81b7ed5d2815c77c21a1c596b35c54611c63e958ee5674c6ac8f91ead19e3e371df8c821c51b2bfd"},
    {"name": "totpVerified", "value": "1"},
    {"name": "g_state", "value": '{"i_l":0,"i_ll":1788290193868,"i_b":"A+0b1Dj5lyby4okgVAhTEYdIAi3TJBGoW1A/gUxB9I4","i_e":{"enable_itp_optimization":24},"i_et":1788290193868}'},
    {"name": "rm_fe", "value": "2f6631856d3362ec"},
]

HEADERS = {
    "Accept": "text/html,application/json",
    "Accept-Language": "en-IN,en;q=0.9",
    "Origin": SITE,
    "Referer": SITE + "/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
}


def req(method, url, body=None):
    h = dict(HEADERS)
    h["Cookie"] = "; ".join(f'{c["name"]}={c["value"]}' for c in COOKIES)
    if body is not None:
        h["Content-Type"] = "application/json"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"ERROR: {e}"


def show(label, status, body):
    print(f"  {label:26} -> {status} | {len(body):>7} bytes | {body[:90].replace(chr(10), ' ')}")


def main():
    print("cookies provided:", [c["name"] for c in COOKIES])
    st, body = req("GET", f"{API}/auth/me")
    show("/auth/me", st, body)
    if st != 200:
        print("  => NOT LOGGED IN (no accessToken/refreshToken in these cookies)\n")

    base = f"{SITE}/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}"

    print("\nquestions:")
    st_q, q = req("GET", f"{base}/attempt")
    show("GET /attempt", st_q, q)
    qmark = q.count('"questionId"')
    print(f"    questionId markers: {qmark} | 'pricing' redirect: {'pricing' in q[:2000]}")
    open("probe_attempt.html", "w", encoding="utf-8").write(q)

    print("\nattempt create/submit (API):")
    for label, url in (("POST start", f"{API}/api/v1/attempts/{TEST_ID}/start"),
                       ("POST submit", f"{API}/api/v1/attempts/{TEST_ID}/submit")):
        s, b = req("POST", url, {"answers": []})
        show(label, s, b)

    print("\nanswers + solutions:")
    st_s, s_body = req("GET", f"{base}/solution")
    show("GET /solution", st_s, s_body)
    print(f"    answersData: {'answersData' in s_body} | correctOption: {s_body.count('correctOption')}")
    open("probe_solution.html", "w", encoding="utf-8").write(s_body)

    print("\nanalysis:")
    st_a, a_body = req("GET", f"{base}/analysis")
    show("GET /analysis", st_a, a_body)
    print(f"    analysisData: {'analysisData' in a_body} | percentile: {a_body.count('percentile')}")
    open("probe_analysis.html", "w", encoding="utf-8").write(a_body)

    print("\n=== VERDICT for these cookies on the PAID test ===")
    print(f"  questions : {'YES' if qmark > 3 else 'NO'}")
    print(f"  answers   : {'YES' if 'answersData' in s_body else 'NO'}")
    print(f"  analysis  : {'YES' if 'analysisData' in a_body else 'NO'}")


if __name__ == "__main__":
    main()
