"""
diagnose_prozorro.py
Запусти це ПЕРШИМ — покаже що реально повертає API і де проблема
"""
import requests
import json

BASE_URL = "https://public-api.prozorro.gov.ua/api/2.5"

print("=" * 60)
print("ДІАГНОСТИКА PROZORRO API")
print("=" * 60)

# Крок 1: отримуємо перший тендер зі списку
print("\n[1] Отримуємо список тендерів...")
r = requests.get(f"{BASE_URL}/tenders", params={"limit": 5}, timeout=15)
print(f"    HTTP статус: {r.status_code}")
data = r.json().get("data", [])
print(f"    Кількість у відповіді: {len(data)}")

if not data:
    print("    ✗ Порожня відповідь!")
    exit()

first_id = data[0]["id"]
print(f"    Перший ID: {first_id}")

# Крок 2: завантажуємо деталі
print(f"\n[2] Завантажуємо деталі тендера {first_id}...")
r2 = requests.get(f"{BASE_URL}/tenders/{first_id}", timeout=15)
tender = r2.json().get("data", {})

print(f"    tenderID : {tender.get('tenderID')}")
print(f"    status   : {tender.get('status')}")
print(f"    title    : {tender.get('title', '')[:60]}")
print(f"    budget   : {tender.get('value', {}).get('amount')} грн")

# Крок 3: дивимось awards
awards = tender.get("awards", [])
print(f"\n[3] Поле 'awards': {len(awards)} записів")
for i, a in enumerate(awards):
    print(f"    awards[{i}].status = '{a.get('status')}'")
    for s in a.get("suppliers", []):
        print(f"      supplier: {s.get('name')} | ЄДРПОУ: {s.get('identifier', {}).get('id')}")

# Крок 4: шукаємо тендери зі статусом complete
print(f"\n[4] Шукаємо тендер зі статусом 'complete' (у них є переможці)...")
for item in data:
    r3 = requests.get(f"{BASE_URL}/tenders/{item['id']}", timeout=15)
    t = r3.json().get("data", {})
    status = t.get("status")
    awards = t.get("awards", [])
    active = [a for a in awards if a.get("status") == "active"]
    print(f"    {t.get('tenderID'):35} status={status:15} awards={len(awards)} active={len(active)}")

# Крок 5: пошук по ДК коду — перевіряємо чи він взагалі працює
print(f"\n[5] Тест пошуку за кодом ДК 71320000-1...")
r4 = requests.get(f"{BASE_URL}/tenders",
                  params={"query": "71320000-1", "limit": 3},
                  timeout=15)
dk_data = r4.json().get("data", [])
print(f"    Знайдено: {len(dk_data)} тендерів")

# Крок 6: пошук по статусу
print(f"\n[6] Тест: тендери зі статусом 'complete'...")
r5 = requests.get(f"{BASE_URL}/tenders",
                  params={"opt_fields": "status,tenderID", "limit": 10},
                  timeout=15)
for item in r5.json().get("data", []):
    print(f"    {item.get('tenderID','?'):35} status={item.get('status','?')}")

print("\n" + "=" * 60)
print("Збережемо повну структуру першого тендера у файл...")
with open("tender_sample.json", "w", encoding="utf-8") as f:
    json.dump(tender, f, ensure_ascii=False, indent=2)
print("Файл: tender_sample.json — відкрий і подивись структуру")