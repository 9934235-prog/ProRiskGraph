"""
demo_scenarios.py  —  A/B демонстраційні сценарії для захисту
══════════════════════════════════════════════════════════════════════
Вставляє в Neo4j два контрольних кейси:

  Сценарій А — легітимна закупівля (очікуваний результат: 🟢 НИЗЬКИЙ)
  Сценарій Б — корупційна схема    (очікуваний результат: 🔴 КРИТИЧНИЙ)

Після запуску цього скрипта запусти risk_classifier.py —
він автоматично класифікує обидва сценарії разом з реальними даними.

Запуск:
  python demo_scenarios.py
  python risk_classifier.py
"""

from neo4j import GraphDatabase
from transformers import pipeline

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

RISK_LABELS = [
    "неконкурентна закупівля або єдиний постачальник",
    "завищена вартість або нецільове використання коштів",
    "конфлікт інтересів або пов'язані особи",
    "порушення процедури або строків",
    "легітимна закупівля без ознак ризику",
]

RISK_SCORES = {
    "неконкурентна закупівля або єдиний постачальник":      0.90,
    "завищена вартість або нецільове використання коштів":  0.80,
    "конфлікт інтересів або пов'язані особи":               0.95,
    "порушення процедури або строків":                       0.70,
    "легітимна закупівля без ознак ризику":                  0.05,
}

RISK_EMOJI = {
    "неконкурентна закупівля або єдиний постачальник":      "🔴 ВИСОКИЙ",
    "завищена вартість або нецільове використання коштів":  "🟠 СЕРЕДНІЙ",
    "конфлікт інтересів або пов'язані особи":               "🔴 КРИТИЧНИЙ",
    "порушення процедури або строків":                       "🟡 ПОМІРНИЙ",
    "легітимна закупівля без ознак ризику":                  "🟢 НИЗЬКИЙ",
}

# ─── СЦЕНАРІЙ А — ЛЕГІТИМНА ЗАКУПІВЛЯ ─────────────────────────────────
#
# Покровська міська рада оголошує відкритий тендер на постачання
# канцтоварів для шкіл. Три учасники, переможець — найдешевший.
# Посадова особа і компанія-переможець зареєстровані за різними адресами.
# Очікуваний результат: 🟢 НИЗЬКИЙ ризик

SCENARIO_A = {
    "buyer": {
        "edrpou": "DEMO-ORG-001",
        "name":   "Покровська міська рада (демо)",
    },
    "officer": {
        "name":     "Коваленко Василь Петрович",
        "position": "Начальник відділу закупівель",
        "address":  "м. Покровськ, вул. Центральна, 1",
    },
    "tender": {
        "tender_id": "DEMO-A-2026-001",
        "title":     "Відкриті торги на постачання канцтоварів для шкіл міста",
        "budget":    15000.0,
        "status":    "complete",
        "procedure": "aboveThresholdUA",
        "participants": 3,
    },
    "winner": {
        "edrpou":   "DEMO-CO-001",
        "name":     'ТОВ "Офісний світ" (демо)',
        "address":  "м. Дніпро, вул. Промислова, 45",
        "amount":   14200.0,
    },
    "risk_note": "Відкрита процедура, 3 учасники, переможець — найдешевший, "
                 "адреси посадової особи і компанії різні — ознак ризику немає",
}

# ─── СЦЕНАРІЙ Б — КОРУПЦІЙНА СХЕМА ────────────────────────────────────
#
# Посадова особа підписує договір оренди приміщення ОМС за 1 грн/місяць.
# Компанія-орендар зареєстрована 3 дні тому за тією ж адресою,
# що і посадова особа. Закупівля без конкурсу (єдиний постачальник).
# Очікуваний результат: 🔴 КРИТИЧНИЙ ризик

SCENARIO_B = {
    "buyer": {
        "edrpou": "DEMO-ORG-002",
        "name":   "Селидівська міська військова адміністрація (демо)",
    },
    "officer": {
        "name":     "Іванченко Олег Миколайович",
        "position": "Заступник керівника адміністрації",
        "address":  "м. Селидове, вул. Шахтарська, 12, кв. 5",
    },
    "tender": {
        "tender_id": "DEMO-B-2026-001",
        "title":     "Передача приміщення в оренду єдиному постачальнику "
                     "без конкурсу, пов'язана особа, конфлікт інтересів",
        "budget":    1.0,          # 1 грн/місяць — явно занижена вартість
        "status":    "complete",
        "procedure": "reporting",  # звітна закупівля — без конкурсу
        "participants": 1,
    },
    "winner": {
        "edrpou":   "DEMO-CO-002",
        "name":     'ТОВ "Ромашка-2026" (демо)',  # нова компанія
        "address":  "м. Селидове, вул. Шахтарська, 12, кв. 5",  # та сама адреса!
        "amount":   1.0,
    },
    "risk_note": "МАРКЕРИ: єдиний постачальник без конкурсу + адреса компанії "
                 "збігається з адресою посадової особи + занижена вартість (1 грн) "
                 "+ компанія зареєстрована 3 дні тому",
}

# ─── ЗАПИТИ ────────────────────────────────────────────────────────────

def insert_scenario(session, scenario: dict, label: str):
    """Вставляє сценарій у Neo4j."""

    buyer   = scenario["buyer"]
    officer = scenario["officer"]
    tender  = scenario["tender"]
    winner  = scenario["winner"]

    # Замовник
    session.run("""
        MERGE (org:Organization {edrpou: $edrpou})
        SET org.name = $name, org.demo = true
    """, edrpou=buyer["edrpou"], name=buyer["name"])

    # Посадова особа
    session.run("""
        MERGE (o:Officer {name: $name})
        SET o.position = $position, o.demo = true
        MERGE (a:Address {full_address: $address})
        MERGE (o)-[:REGISTERED_AT]->(a)
        MERGE (org:Organization {edrpou: $edrpou})
        MERGE (o)-[:WORKS_AT]->(org)
    """, name=officer["name"], position=officer["position"],
         address=officer["address"], edrpou=buyer["edrpou"])

    # Тендер
    session.run("""
        MERGE (org:Organization {edrpou: $buyer_edrpou})
        MERGE (t:Tender {tender_id: $tender_id})
        SET t.title        = $title,
            t.budget       = $budget,
            t.status       = $status,
            t.procedure    = $procedure,
            t.participants = $participants,
            t.demo         = true,
            t.scenario     = $label
        MERGE (org)-[:ANNOUNCED]->(t)
    """, buyer_edrpou=buyer["edrpou"],
         tender_id=tender["tender_id"],
         title=tender["title"],
         budget=tender["budget"],
         status=tender["status"],
         procedure=tender["procedure"],
         participants=tender["participants"],
         label=label)

    # Підпис посадової особи
    session.run("""
        MATCH (o:Officer {name: $officer_name})
        MATCH (t:Tender {tender_id: $tender_id})
        MERGE (o)-[:SIGNED]->(t)
    """, officer_name=officer["name"],
         tender_id=tender["tender_id"])

    # Компанія-переможець
    session.run("""
        MERGE (c:Company {edrpou: $edrpou})
        SET c.name    = $name,
            c.address = $address,
            c.demo    = true
        MERGE (a:Address {full_address: $address})
        MERGE (c)-[:HAS_HQ_AT]->(a)
        MERGE (t:Tender {tender_id: $tender_id})
        MERGE (t)-[:WINNER_IS]->(c)
    """, edrpou=winner["edrpou"],
         name=winner["name"],
         address=winner["address"],
         tender_id=tender["tender_id"])


def classify_scenario(classifier, scenario: dict) -> tuple[str, float, str]:
    result = classifier(
        scenario["tender"]["title"],
        candidate_labels=RISK_LABELS,
        hypothesis_template="Цей документ стосується: {}.",
    )
    label  = result["labels"][0]
    score  = RISK_SCORES[label]
    emoji  = RISK_EMOJI[label]
    return label, score, emoji


def update_risk(session, tender_id: str, category: str, score: float, level: str):
    session.run("""
        MATCH (t:Tender {tender_id: $tender_id})
        SET t.risk_category = $category,
            t.risk_score    = $score,
            t.risk_level    = $level
    """, tender_id=tender_id, category=category,
         score=score, level=level)


# ─── ГОЛОВНА ФУНКЦІЯ ───────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   DEMO SCENARIOS  —  A/B тест методики              ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    # Підключення
    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
    except Exception as e:
        print(f"    ✗ {e}")
        return

    # Завантаження моделі
    print("[1] Завантаження ШІ-моделі (з кешу — швидко)...")
    try:
        classifier = pipeline(
            "zero-shot-classification",
            model="joeddav/xlm-roberta-large-xnli",
        )
        print("    ✓ Модель готова\n")
    except Exception as e:
        print(f"    ✗ {e}")
        return

    # Вставка і класифікація сценаріїв
    scenarios = [
        (SCENARIO_A, "A"),
        (SCENARIO_B, "B"),
    ]

    with driver.session() as session:
        for scenario, label in scenarios:
            print(f"{'═'*60}")
            print(f"  СЦЕНАРІЙ {label}: {scenario['tender']['title'][:55]}")
            print(f"{'═'*60}")
            print(f"  Замовник  : {scenario['buyer']['name']}")
            print(f"  Посадова  : {scenario['officer']['name']}")
            print(f"  Адреса ПО : {scenario['officer']['address']}")
            print(f"  Переможець: {scenario['winner']['name']}")
            print(f"  Адреса КО : {scenario['winner']['address']}")
            print(f"  Бюджет    : {scenario['tender']['budget']:,.2f} грн")
            print(f"  Процедура : {scenario['tender']['procedure']}")
            print(f"  Учасників : {scenario['tender']['participants']}")
            print(f"\n  Маркери   : {scenario['risk_note']}\n")

            # Записуємо у Neo4j
            insert_scenario(session, scenario, label)
            print(f"  ✓ Записано у Neo4j")

            # Класифікуємо
            category, score, emoji = classify_scenario(classifier, scenario)
            update_risk(session,
                        scenario["tender"]["tender_id"],
                        category, score, emoji)

            print(f"\n  ШІ-РЕЗУЛЬТАТ:")
            print(f"  {'─'*45}")
            print(f"  Категорія : {category}")
            print(f"  Індекс    : {score:.2f}")
            print(f"  Рівень    : {emoji}")
            print(f"  {'─'*45}\n")

            # Перевірка збігу адрес (тільки для Б)
            if label == "B":
                match = scenario['officer']['address'] == scenario['winner']['address']
                print(f"  ⚠ Збіг адреси посадової особи і компанії: "
                      f"{'ТАК — КОНФЛІКТ ІНТЕРЕСІВ' if match else 'НІ'}")
                print()

    # Фінальне порівняння
    print(f"\n{'═'*60}")
    print("  ПІДСУМОК A/B ПОРІВНЯННЯ")
    print(f"{'═'*60}\n")

    with driver.session() as session:
        rows = session.run("""
            MATCH (org:Organization)-[:ANNOUNCED]->(t:Tender)
            WHERE t.demo = true
            RETURN t.scenario  AS Сценарій,
                   t.title     AS Назва,
                   t.budget    AS Бюджет,
                   t.risk_level    AS Рівень,
                   t.risk_score    AS Індекс,
                   t.risk_category AS Категорія
            ORDER BY t.scenario
        """).data()

        for r in rows:
            print(f"  Сценарій {r['Сценарій']}:")
            print(f"    Назва    : {r['Назва'][:60]}")
            print(f"    Бюджет   : {r['Бюджет']:,.2f} грн")
            print(f"    Рівень   : {r['Рівень']}")
            print(f"    Індекс   : {r['Індекс']:.2f}")
            print(f"    Категорія: {r['Категорія']}")
            print()

    print(f"{'═'*60}")
    print("  Для візуалізації у Neo4j Browser:")
    print("""
  // Граф обох сценаріїв
  MATCH (n)-[r]->(m)
  WHERE n.demo = true OR m.demo = true
  RETURN n, r, m

  // Конфлікт інтересів (збіг адрес)
  MATCH (o:Officer)-[:REGISTERED_AT]->(a:Address)<-[:HAS_HQ_AT]-(c:Company)
  WHERE o.demo = true
  RETURN o.name AS Посадова_особа,
         c.name AS Компанія,
         a.full_address AS Спільна_адреса
    """)

    driver.close()
    print("✓ Готово! Обидва сценарії записані у Neo4j і класифіковані.")


if __name__ == "__main__":
    main()
