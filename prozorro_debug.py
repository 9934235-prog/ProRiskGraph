"""
prozorro_debug.py — Діагностика Prozorro API для конкретного ЄДРПОУ
Запусти: python prozorro_debug.py
"""

import requests
import json

TARGET_EDRPOU = "24604168"
API_BASE = "https://public-api.prozorro.gov.ua/api/2.5"

def test(label, url, params=None):
    print(f"\n{'─'*60}")
    print(f"ТЕСТ: {label}")
    full = requests.Request('GET', url, params=params).prepare().url
    print(f"URL : {full}")
    try:
        r = requests.get(url, params=params, timeout=15)
        print(f"HTTP: {r.status_code}")
        data = r.json()
        tenders = data.get("data", [])
        print(f"Тендерів у відповіді: {len(tenders)}")
        matched = 0
        for t in tenders:
            edrpou = str(t.get("procuringEntity", {}).get("identifier", {}).get("id", "")).strip()
            name   = t.get("procuringEntity", {}).get("name", "?")[:50]
            tid    = t.get("tenderID", "?")
            if edrpou == TARGET_EDRPOU:
                matched += 1
                print(f"  ✓ ЗНАЙДЕНО: {tid} | {name}")
            else:
                print(f"  · {edrpou} | {name[:40]}")
        print(f"Збіг із {TARGET_EDRPOU}: {matched} з {len(tenders)}")
        np = data.get("next_page", {})
        print(f"next_page offset: {np.get('offset', 'відсутній')}")
        return data
    except Exception as e:
        print(f"ПОМИЛКА: {e}")
        return None


# ── ТЕСТ 1: Чи взагалі API відповідає ──────────────────────────
test(
    "Базовий запит (перші 5 тендерів)",
    f"{API_BASE}/tenders",
    {"limit": 5, "opt_fields": "tenderID,procuringEntity"}
)

# ── ТЕСТ 2: Фільтр по edrpou (параметр) ────────────────────────
test(
    "Фільтр ?edrpou=24604168",
    f"{API_BASE}/tenders",
    {"limit": 10, "edrpou": TARGET_EDRPOU,
     "opt_fields": "tenderID,procuringEntity,status"}
)

# ── ТЕСТ 3: Пошук через /tenders з procuringEntity.identifier.id ─
test(
    "Фільтр ?procuringEntity.identifier.id=24604168",
    f"{API_BASE}/tenders",
    {"limit": 10,
     "procuringEntity.identifier.id": TARGET_EDRPOU,
     "opt_fields": "tenderID,procuringEntity,status"}
)

# ── ТЕСТ 4: Найновіші тендери (зворотній порядок) ───────────────
data = test(
    "Найновіші тендери (descending dateModified)",
    f"{API_BASE}/tenders",
    {"limit": 5,
     "reverse": "1",
     "opt_fields": "tenderID,procuringEntity,status,dateModified"}
)

# ── ТЕСТ 5: Prozorro Search API (інший endpoint) ────────────────
print(f"\n{'─'*60}")
print("ТЕСТ: Prozorro Search API")
search_url = "https://prozorro.gov.ua/api/search/tenders"
params = {
    "buyer_id": TARGET_EDRPOU,
    "limit": 5
}
full = requests.Request('GET', search_url, params=params).prepare().url
print(f"URL : {full}")
try:
    r = requests.get(search_url, params=params, timeout=15)
    print(f"HTTP: {r.status_code}")
    print(f"Відповідь (перші 500 символів): {r.text[:500]}")
except Exception as e:
    print(f"ПОМИЛКА: {e}")

# ── ТЕСТ 6: bi.prozorro.org (аналітичний API) ──────────────────
print(f"\n{'─'*60}")
print("ТЕСТ: bi.prozorro.org (аналітичний)")
bi_url = "https://bi.prozorro.org/api/1/tenders/_search"
body = {
    "query": {
        "term": {"procuringEntity.identifier.id": TARGET_EDRPOU}
    },
    "size": 5,
    "_source": ["tenderID", "procuringEntity.name", "status"]
}
try:
    r = requests.post(bi_url, json=body, timeout=15)
    print(f"HTTP: {r.status_code}")
    print(f"Відповідь (перші 500 символів): {r.text[:500]}")
except Exception as e:
    print(f"ПОМИЛКА: {e}")

print(f"\n{'═'*60}")
print("Діагностика завершена.")
print(f"Якщо всі тести дають 0 — скопіюй весь вивід і надішли.")
