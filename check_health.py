import requests
for port in [5000, 5001]:
    try:
        r = requests.get(f'http://127.0.0.1:{port}/healthz', timeout=10)
        print(port, r.status_code, r.text)
    except Exception as exc:
        print(port, 'ERR', exc)
