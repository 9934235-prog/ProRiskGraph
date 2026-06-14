"""
risk_classifier.py  —  Модуль Б: класифікатор корупційних ризиків
══════════════════════════════════════════════════════════════════════
Використовує zero-shot класифікацію через xlm-roberta-large-xnli.
Не потребує навчання і розміченого датасету.

Що робить:
  1. Підключається до Neo4j і бере всі збережені тендери
  2. Для кожного тендера аналізує назву через ШІ-модель
  3. Визначає категорію ризику і числовий індекс (0.0 — 1.0)
  4. Записує результат назад у Neo4j (t.risk_category, t.risk_score)
  5. Виводить підсумковий звіт

Встановити один раз:
  pip install transformers torch
"""

from transformers import pipeline
from neo4j import GraphDatabase
import time

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

# Категорії ризику — модель сама визначає найближчу
RISK_LABELS = [
    "неконкурентна закупівля або єдиний постачальник",
    "завищена вартість або нецільове використання коштів",
    "конфлікт інтересів або пов'язані особи",
    "порушення процедури або строків",
    "легітимна закупівля без ознак ризику",
]

# Числовий індекс ризику для кожної категорії (0.0 = безпечно, 1.0 = критично)
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

# Cypher: оновити тендер результатами класифікації
UPDATE_QUERY = """
MATCH (t:Tender {tender_id: $tender_id})
SET t.risk_category = $risk_category,
    t.risk_score    = $risk_score,
    t.risk_level    = $risk_level
"""

# Cypher: отримати всі тендери для аналізу
GET_TENDERS_QUERY = """
MATCH (buyer:Organization)-[:ANNOUNCED]->(t:Tender)
RETURN t.tender_id AS id,
       t.title     AS title,
       t.budget    AS budget,
       buyer.name  AS buyer
ORDER BY t.budget DESC
"""


def load_model():
    print("[1] Завантаження ШІ-моделі xlm-roberta-large-xnli...")
    print("    (перший раз ~1.5 ГБ з інтернету, далі з кешу)\n")
    try:
        classifier = pipeline(
            "zero-shot-classification",
            model="joeddav/xlm-roberta-large-xnli",
        )
        print("    ✓ Модель завантажена\n")
        return classifier
    except Exception as e:
        print(f"    ✗ Помилка: {e}")
        return None


def classify(classifier, text: str) -> tuple[str, float, str]:
    """
    Повертає (категорія, індекс_ризику, рівень_ризику).
    """
    result = classifier(
        text,
        candidate_labels=RISK_LABELS,
        hypothesis_template="Цей документ стосується: {}.",
    )
    top_label = result["labels"][0]
    score     = RISK_SCORES[top_label]
    level     = RISK_EMOJI[top_label]
    return top_label, score, level


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   МОДУЛЬ Б — Класифікатор корупційних ризиків       ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    # Підключення до Neo4j
    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
    except Exception as e:
        print(f"    ✗ {e}")
        return

    # Завантаження моделі
    classifier = load_model()
    if not classifier:
        return

    # Отримання тендерів з Neo4j
    print("[2] Отримання тендерів з Neo4j...")
    with driver.session() as session:
        tenders = session.run(GET_TENDERS_QUERY).data()

    print(f"    Знайдено: {len(tenders)} тендерів\n")
    if not tenders:
        print("    ⚠ Немає даних. Спочатку запусти prozorro_to_neo4j_v3.py")
        return

    # Класифікація
    print("[3] Класифікація ризиків...\n")
    print(f"  {'№':3} {'Тендер':25} {'Бюджет':>12} {'Рівень':15} {'Категорія'}")
    print("  " + "─" * 100)

    results = []
    with driver.session() as session:
        for i, t in enumerate(tenders, 1):
            title     = t.get("title") or "без назви"
            tender_id = t.get("id", "")
            budget    = t.get("budget", 0) or 0
            buyer     = t.get("buyer", "")

            try:
                category, score, level = classify(classifier, title)
            except Exception as e:
                print(f"  [{i:3}] ✗ Помилка класифікації: {e}")
                continue

            # Записуємо у Neo4j
            session.run(UPDATE_QUERY,
                        tender_id=tender_id,
                        risk_category=category,
                        risk_score=score,
                        risk_level=level)

            results.append({
                "id":       tender_id,
                "title":    title,
                "budget":   budget,
                "buyer":    buyer,
                "category": category,
                "score":    score,
                "level":    level,
            })

            print(f"  [{i:3}] {tender_id[:23]:25} "
                  f"{budget:>12,.0f} грн  "
                  f"{level:20} {category[:45]}")

            time.sleep(0.1)

    # Підсумковий звіт
    print("\n" + "═" * 60)
    print("  ПІДСУМКОВИЙ ЗВІТ РИЗИКІВ")
    print("═" * 60)

    # Групування по рівнях
    critical = [r for r in results if r["score"] >= 0.90]
    high     = [r for r in results if 0.70 <= r["score"] < 0.90]
    low      = [r for r in results if r["score"] < 0.70]

    print(f"\n  🔴 Критичний/Високий ризик : {len(critical)} тендерів")
    for r in critical:
        print(f"     • {r['id'][:30]:32} {r['budget']:>12,.0f} грн  {r['buyer'][:35]}")

    print(f"\n  🟠 Середній/Помірний ризик : {len(high)} тендерів")
    for r in high:
        print(f"     • {r['id'][:30]:32} {r['budget']:>12,.0f} грн  {r['buyer'][:35]}")

    print(f"\n  🟢 Низький ризик           : {len(low)} тендерів")

    total_risky = sum(r["budget"] for r in results if r["score"] >= 0.70)
    print(f"\n  Загальна сума тендерів з ризиком ≥ 0.7: {total_risky:,.0f} грн")

    print("\n" + "═" * 60)
    print("  Результати записано у Neo4j.")
    print("  Запит для перевірки у Neo4j Browser:")
    print("""
  MATCH (t:Tender)
  WHERE t.risk_score >= 0.7
  RETURN t.tender_id, t.title, t.budget,
         t.risk_level, t.risk_category
  ORDER BY t.risk_score DESC
    """)

    driver.close()
    print("✓ Готово!")


if __name__ == "__main__":
    main()
