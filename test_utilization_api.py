import requests
import json

tests = [
    ("Only Sep 4", "2026-09-04", "2026-09-04"),
    ("Only Sep 7", "2026-09-07", "2026-09-07"),
    ("Sep 4 to 8", "2026-09-04", "2026-09-08"),
]

for label, fr, to in tests:
    url = "http://127.0.0.1:8000/api/machines/utilization/state?from=" + fr + "&to=" + to
    r = requests.get(url)
    data = r.json()
    print("\n=== " + label + " (" + fr + " -> " + to + ") | total records: " + str(len(data)) + " ===")
    for entry in data:
        print("  " + entry["mc_id"] + "  date=" + entry["date"] + "  runtime=" + str(entry["runtime"]) + "s  util=" + str(entry["utilization_percent"]) + "%")
