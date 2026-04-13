import requests

# Test the endpoints
base_url = "http://127.0.0.1:5000"

endpoints = [
    ("/api/v1/certify", "POST"),
    ("/api/evaluate", "POST"),
    ("/api/v1/evaluate", "POST"),
]

print("--- Routing Test ---")
for path, method in endpoints:
    url = f"{base_url}{path}"
    try:
        if method == "POST":
            resp = requests.post(url, json={"test": True}, timeout=2)
        else:
            resp = requests.get(url, timeout=2)
        print(f"{method} {path} -> Status: {resp.status_code}")
    except Exception as e:
        print(f"{method} {path} -> Error: {e}")
