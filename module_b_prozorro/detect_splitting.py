"""
detect_splitting.py  —  Виявлення штучного дроблення закупівель
══════════════════════════════════════════════════════════════════════
Офіційний індикатор НАЗК: "штучне розділення предмету закупівлі для
уникнення конкурентних процедур" — один із найпоширеніших типових
корупційних ризиків у публічних закупівлях (Реєстр корупційних
ризиків, п. 1.2: "Поділ одного предмета для укладення прямого
договору або застосування спрощеної закупівлі").

Юридичні пороги (п. 11 Особливостей №1178), нижче яких можна укладати
прямі договори без е-системи:
  - товари та послуги (крім поточного ремонту): до 100 000 грн
  - послуги з поточного ремонту: до 200 000 грн
  - роботи: до 1 500 000 грн

Логіка виявлення:
  Якщо один замовник протягом одного року уклав КІЛЬКА окремих прямих
  договорів (procedure = "закупівля без використання електронної системи")
  у тій самій товарній категорії (код ДК 021/CPV), і СУМА цих договорів
  перевищує законний поріг — це формальна ознака штучного дроблення,
  навіть якщо кожен договір окремо виглядає "малим і безпечним".

Запуск:
  python detect_splitting.py
"""

from neo4j import GraphDatabase
import re

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

# Законодавчі пороги (п. 11 Особливостей №1178)
THRESHOLD_GOODS_SERVICES = 100_000   # товари та послуги (крім поточного ремонту)
THRESHOLD_REPAIR         = 200_000   # послуги з поточного ремонту
THRESHOLD_WORKS          = 1_500_000  # роботи

# Cypher-запит: беремо всі прямі договори, групування за категорією ДК 021
# робимо в Python (надійніше за спроби парсити regex прямо в Cypher,
# бо в title зустрічаються різні типи лапок — типографські й прямі)
DETECT_SPLITTING_QUERY = """
MATCH (org:Organization)-[:ANNOUNCED]->(t)
WHERE (t:LowRisk OR t:MediumRisk OR t:HighRisk)
  AND t.procedure = 'закупівля без використання електронної системи'
RETURN org.name AS organization, org.edrpou AS edrpou,
       t.tender_id AS tender_id, t.title AS title, t.budget AS budget
"""


def classify_threshold(title: str) -> int:
    """Дуже спрощене визначення застосовного порогу за ключовими словами в назві."""
    title_lower = (title or "").lower()
    if "поточний ремонт" in title_lower or "ремонт" in title_lower:
        return THRESHOLD_REPAIR
    if any(w in title_lower for w in ["роботи", "будівництво", "реконструкція", "реставрація"]):
        return THRESHOLD_WORKS
    return THRESHOLD_GOODS_SERVICES


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Виявлення ознак штучного дроблення закупівель           ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    print("[0] Підключено до Neo4j\n")

    with driver.session() as session:
        rows = session.run(DETECT_SPLITTING_QUERY).data()

    print(f"[1] Прямих договорів (procedure = 'без е-системи') у базі: {len(rows)}\n")

    # Витягуємо код ДК 021 (формат XXXXXXXX-X) з title у Python —
    # надійніше за Cypher regex, бо title містить різні типи лапок
    # (типографські "" і прямі "")
    cpv_pattern = re.compile(r"(\d{8}-\d)")

    groups = {}
    no_cpv_found = 0
    for r in rows:
        match = cpv_pattern.search(r["title"] or "")
        if not match:
            no_cpv_found += 1
            continue
        cpv_code = match.group(1)
        year = r["tender_id"][3:7]  # UA-2026-... -> "2026"
        key = (r["organization"], cpv_code, year)
        groups.setdefault(key, []).append(r)

    print(f"[2] Тендерів без розпізнаного коду ДК 021 у назві: {no_cpv_found}")
    print(f"[3] Унікальних груп (замовник + категорія ДК 021 + рік): {len(groups)}\n")
    print("    Примітка: групування СВІДОМО прив'язане до календарного року —")
    print("    дроблення означає поділ ОДНІЄЇ річної потреби на кілька договорів")
    print("    у той самий період, а не окремі щорічні договори на послуги")
    print("    тривалого характеру (опалення, охорона), які є нормальною практикою.\n")

    multi_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    print(f"[4] З них груп з кількома (≥2) окремими прямими договорами "
          f"В МЕЖАХ ОДНОГО РОКУ: {len(multi_groups)}\n")

    flagged = []
    for (org, cpv_code, year), tenders in multi_groups.items():
        total_budget = sum(t["budget"] for t in tenders)
        threshold = classify_threshold(tenders[0]["title"])
        if total_budget > threshold:
            flagged.append({
                "organization": org, "cpv_code": cpv_code, "year": year,
                "tenders": tenders, "total_budget": total_budget,
                "threshold": threshold,
            })

    print(f"[5] З них перевищують законний поріг (можлива ознака дроблення): "
          f"{len(flagged)}\n")

    if not flagged:
        print("    Жодної групи з перевищенням порогу не знайдено на цій вибірці")
        print("    в межах одного календарного року.")
        print("    Це очікувано на малій тестовій вибірці (32 тендери) — для")
        print("    надійного виявлення реальних випадків дроблення потрібне")
        print("    повне довантаження procedure для всіх 1481 тендерів.")
    else:
        print("═" * 70)
        for f in flagged:
            print(f"\n  ⚠ {f['organization']}")
            print(f"    Категорія ДК 021: {f['cpv_code']}, рік: {f['year']}")
            print(f"    Кількість окремих договорів у цьому ж році: {len(f['tenders'])}")
            print(f"    Сумарний бюджет за рік: {f['total_budget']:,.2f} грн "
                  f"(поріг: {f['threshold']:,} грн)")
            print(f"    Перевищення порогу на: {f['total_budget'] - f['threshold']:,.2f} грн")
            print(f"    Договори:")
            for t in f["tenders"]:
                print(f"      • {t['tender_id']}: {t['budget']:,.2f} грн — {t['title'][:70]}")

    # Показуємо й групи, що НЕ перевищують порогу — для прозорості діагностики
    if multi_groups and not flagged:
        print("\n" + "─" * 70)
        print("  Знайдені групи з кількома договорами в межах року (для довідки):")
        for (org, cpv_code, year), tenders in multi_groups.items():
            total = sum(t["budget"] for t in tenders)
            print(f"    {org} | ДК {cpv_code} | {year}: {len(tenders)} договори, "
                  f"разом {total:,.2f} грн "
                  f"(поріг {classify_threshold(tenders[0]['title']):,} грн)")

    driver.close()
    print("\n✓ Готово.")


if __name__ == "__main__":
    main()
