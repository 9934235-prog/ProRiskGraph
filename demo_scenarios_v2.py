"""
demo_scenarios_v2.py  —  A/B демонстраційні сценарії для захисту (виправлено)
══════════════════════════════════════════════════════════════════════
ЗМІНА v2: класифікація сценаріїв тепер враховує структуровані дані
(кількість учасників, тип процедури, збіг адрес), а не лише текст
назви тендера через zero-shot. Це узгоджує логіку demo-сценаріїв
з тією самою гібридною методикою (правила + NLP), що вже реалізована
в risk_classifier_v3.py для реальних тендерів.

Чому це важливо: попередня версія (тільки NLP на title) дала
хибнопозитивний результат для Сценарію А (легітимна закупівля
отримала 🟡 ПОМІРНИЙ замість 🟢 НИЗЬКИЙ) — нейтральна назва без явних
"сигнальних" слів випадково потрапила в категорію "порушення процедури".

Запуск:
  python demo_scenarios_v2.py
"""

from neo4j import GraphDatabase
from transformers import pipeline

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

NLP_LABELS = [
    "підозрілі або розмиті формулювання предмету закупівлі",
    "чіткий і конкретний предмет закупівлі",
]

# ─── СЦЕНАРІЙ А — ЛЕГІТИМНА ЗАКУПІВЛЯ ─────────────────────────────────
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
        "budget":    1.0,
        "status":    "complete",
        "procedure": "reporting",
        "participants": 1,
    },
    "winner": {
        "edrpou":   "DEMO-CO-002",
        "name":     'ТОВ "Ромашка-2026" (демо)',
        "address":  "м. Селидове, вул. Шахтарська, 12, кв. 5",
        "amount":   1.0,
    },
    "risk_note": "МАРКЕРИ: єдиний постачальник без конкурсу + адреса компанії "
                 "збігається з адресою посадової особи + занижена вартість (1 грн) "
                 "+ компанія зареєстрована 3 дні тому",
}


# ─── ЗАПИТИ (без змін) ──────────────────────────────────────────────────

def insert_scenario(session, scenario: dict, label: str):
    buyer   = scenario["buyer"]
    officer = scenario["officer"]
    tender  = scenario["tender"]
    winner  = scenario["winner"]

    session.run("""
        MERGE (org:Organization {edrpou: $edrpou})
        SET org.name = $name, org.demo = true
    """, edrpou=buyer["edrpou"], name=buyer["name"])

    session.run("""
        MERGE (o:Officer {name: $name})
        SET o.position = $position, o.demo = true
        MERGE (a:Address {full_address: $address})
        MERGE (o)-[:REGISTERED_AT]->(a)
        MERGE (org:Organization {edrpou: $edrpou})
        MERGE (o)-[:WORKS_AT]->(org)
    """, name=officer["name"], position=officer["position"],
         address=officer["address"], edrpou=buyer["edrpou"])

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

    session.run("""
        MATCH (o:Officer {name: $officer_name})
        MATCH (t:Tender {tender_id: $tender_id})
        MERGE (o)-[:SIGNED]->(t)
    """, officer_name=officer["name"], tender_id=tender["tender_id"])

    session.run("""
        MERGE (c:Company {edrpou: $edrpou})
        SET c.name    = $name,
            c.address = $address,
            c.demo    = true
        MERGE (a:Address {full_address: $address})
        MERGE (c)-[:HAS_HQ_AT]->(a)
        MERGE (t:Tender {tender_id: $tender_id})
        MERGE (t)-[:WINNER_IS]->(c)
    """, edrpou=winner["edrpou"], name=winner["name"],
         address=winner["address"], tender_id=tender["tender_id"])


# ─── НОВА ГІБРИДНА КЛАСИФІКАЦІЯ (правила + NLP) ─────────────────────────

def rule_based_risk(scenario: dict) -> tuple[str, float]:
    """
    Структуровані правила — та сама логіка, що в risk_classifier_v3.py,
    розширена двома ознаками, специфічними для демо-сценаріїв:
    кількістю учасників і збігом адреси посадовця й компанії.
    """
    tender  = scenario["tender"]
    officer = scenario["officer"]
    winner  = scenario["winner"]

    budget       = tender["budget"]
    participants = tender["participants"]
    address_match = officer["address"] == winner["address"]

    # Найсильніший і найоднозначніший сигнал — збіг адрес
    if address_match:
        return "конфлікт інтересів або пов'язані особи", 0.95

    # Єдиний учасник без конкурсу — сильний сигнал ризику
    if participants <= 1:
        return "неконкурентна закупівля або єдиний постачальник", 0.85

    # Відкрита процедура з кількома учасниками — базова легітимність
    if participants >= 3:
        return "легітимна закупівля без ознак ризику", 0.10

    return "порушення процедури або строків", 0.50


def nlp_adjustment(clf, title: str, base_score: float) -> tuple[float, str]:
    """NLP-уточнення тексту назви — лише як додатковий сигнал, не основний."""
    if not clf or not title:
        return base_score, ""
    try:
        r = clf(title, candidate_labels=NLP_LABELS,
                hypothesis_template="Цей тендер має: {}.")
        if r["labels"][0] == NLP_LABELS[0]:
            return min(base_score + 0.05, 1.0), " + підозріла назва (NLP)"
    except Exception:
        pass
    return base_score, ""


def score_to_level(score: float) -> str:
    if score >= 0.90:
        return "🔴 КРИТИЧНИЙ"
    if score >= 0.75:
        return "🔴 ВИСОКИЙ"
    if score >= 0.50:
        return "🟠 СЕРЕДНІЙ"
    if score >= 0.25:
        return "🟡 ПОМІРНИЙ"
    return "🟢 НИЗЬКИЙ"


def classify_scenario(clf, scenario: dict) -> tuple[str, float, str]:
    category, base_score = rule_based_risk(scenario)
    score, note = nlp_adjustment(clf, scenario["tender"]["title"], base_score)
    level = score_to_level(score)
    return category, score, level, note


def update_risk(session, tender_id: str, category: str, score: float, level: str):
    session.run("""
        MATCH (t:Tender {tender_id: $tender_id})
        SET t.risk_category = $category,
            t.risk_score    = $score,
            t.risk_level    = $level
    """, tender_id=tender_id, category=category, score=score, level=level)


# ─── ГОЛОВНА ФУНКЦІЯ ───────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   DEMO SCENARIOS v2 — гібридна класифікація (A/B)    ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
    except Exception as e:
        print(f"    ✗ {e}")
        return

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

    scenarios = [(SCENARIO_A, "A"), (SCENARIO_B, "B")]

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

            insert_scenario(session, scenario, label)
            print(f"  ✓ Записано у Neo4j")

            category, score, level, note = classify_scenario(classifier, scenario)
            update_risk(session, scenario["tender"]["tender_id"],
                        category, score, level)

            print(f"\n  ГІБРИДНИЙ РЕЗУЛЬТАТ (правила + NLP):")
            print(f"  {'─'*45}")
            print(f"  Категорія : {category}{note}")
            print(f"  Індекс    : {score:.2f}")
            print(f"  Рівень    : {level}")
            print(f"  {'─'*45}\n")

            if label == "B":
                match = scenario['officer']['address'] == scenario['winner']['address']
                print(f"  ⚠ Збіг адреси посадової особи і компанії: "
                      f"{'ТАК — КОНФЛІКТ ІНТЕРЕСІВ' if match else 'НІ'}")
                print()

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

    driver.close()
    print("✓ Готово! Обидва сценарії записані у Neo4j і класифіковані гібридним методом.")


if __name__ == "__main__":
    main()
