"""
risk_classifier_v2.py  —  Класифікатор корупційних ризиків (оптимізований)
══════════════════════════════════════════════════════════════════════════════
ЗМІНИ v2:
  - Батчинг: модель обробляє одразу по BATCH_SIZE тендерів (швидше у 3-5x)
  - Відновлення: пропускає вже класифіковані тендери (можна переривати)
  - Прогрес-бар без зовнішніх бібліотек
  - Топ-20 ризикових тендерів у підсумку

Запуск:
  python risk_classifier_v2.py
"""

from transformers import pipeline
from neo4j import GraphDatabase
import time

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

BATCH_SIZE     = 8    # скільки тендерів за раз передавати в модель
                      # збільш до 16 якщо є ≥8 ГБ RAM, зменш до 4 якщо падає

RISK_LABELS = [
    "неконкурентна закупівля або єдиний постачальник",
    "завищена вартість або нецільове використання коштів",
    "конфлікт інтересів або пов'язані особи",
    "порушення процедури або строків",
    "легітимна закупівля без ознак ризику",
]

RISK_SCORES = {
    "неконкурентна закупівля або єдиний постачальник":     0.90,
    "завищена вартість або нецільове використання коштів": 0.80,
    "конфлікт інтересів або пов'язані особи":              0.95,
    "порушення процедури або строків":                      0.70,
    "легітимна закупівля без ознак ризику":                 0.05,
}

RISK_LEVEL = {
    "неконкурентна закупівля або єдиний постачальник":     "🔴 ВИСОКИЙ",
    "завищена вартість або нецільове використання коштів": "🟠 СЕРЕДНІЙ",
    "конфлікт інтересів або пов'язані особи":              "🔴 КРИТИЧНИЙ",
    "порушення процедури або строків":                      "🟡 ПОМІРНИЙ",
    "легітимна закупівля без ознак ризику":                 "🟢 НИЗЬКИЙ",
}

# ─── Cypher ──────────────────────────────────────────────────────────────────

# Тільки ті, що ще не класифіковані (підтримка відновлення)
GET_TENDERS_QUERY = """
MATCH (org:Organization)-[:ANNOUNCED]->(t:Tender)
WHERE t.risk_score IS NULL
RETURN t.tender_id AS id,
       t.title     AS title,
       t.budget    AS budget,
       org.name    AS buyer
ORDER BY t.budget DESC
"""

# Усі тендери для фінального звіту
GET_ALL_QUERY = """
MATCH (t:Tender)
WHERE t.risk_score IS NOT NULL
RETURN t.tender_id    AS id,
       t.title        AS title,
       t.budget       AS budget,
       t.risk_score   AS score,
       t.risk_level   AS level,
       t.risk_category AS category
ORDER BY t.risk_score DESC, t.budget DESC
"""

UPDATE_QUERY = """
MATCH (t:Tender {tender_id: $tender_id})
SET t.risk_category = $risk_category,
    t.risk_score    = $risk_score,
    t.risk_level    = $risk_level
"""

# ─── ПРОГРЕС-БАР ─────────────────────────────────────────────────────────────

def progress_bar(current, total, width=40):
    pct   = current / total if total else 0
    filled = int(width * pct)
    bar   = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {current}/{total} ({pct*100:.1f}%)"

# ─── NEO4J ───────────────────────────────────────────────────────────────────

def connect_neo4j():
    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
        return driver
    except Exception as e:
        print(f"    ✗ {e}")
        return None

# ─── МОДЕЛЬ ──────────────────────────────────────────────────────────────────

def load_model():
    print("[1] Завантаження моделі xlm-roberta-large-xnli...")
    print("    (перший раз ~1.5 ГБ, далі з кешу)\n")
    try:
        clf = pipeline(
            "zero-shot-classification",
            model="joeddav/xlm-roberta-large-xnli",
        )
        print("    ✓ Модель готова\n")
        return clf
    except Exception as e:
        print(f"    ✗ {e}")
        return None

# ─── КЛАСИФІКАЦІЯ БАТЧЕМ ─────────────────────────────────────────────────────

def classify_batch(clf, texts: list[str]) -> list[tuple[str, float, str]]:
    """
    Класифікує список текстів за один виклик моделі.
    Повертає список (категорія, score, рівень).
    """
    results = clf(
        texts,
        candidate_labels=RISK_LABELS,
        hypothesis_template="Цей документ стосується: {}.",
    )
    # Якщо один текст — clf повертає dict, а не list
    if isinstance(results, dict):
        results = [results]

    output = []
    for r in results:
        top = r["labels"][0]
        output.append((top, RISK_SCORES[top], RISK_LEVEL[top]))
    return output

# ─── ГОЛОВНА ФУНКЦІЯ ─────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   МОДУЛЬ Б v2 — Класифікатор корупційних ризиків        ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    driver = connect_neo4j()
    if not driver:
        return

    clf = load_model()
    if not clf:
        driver.close()
        return

    # ── Завантаження некласифікованих тендерів ───────────────────
    print("[2] Завантаження некласифікованих тендерів...")
    with driver.session() as session:
        tenders = session.run(GET_TENDERS_QUERY).data()

    total = len(tenders)
    if total == 0:
        print("    ✓ Всі тендери вже класифіковано!\n")
    else:
        print(f"    Залишилось класифікувати: {total}\n")

    # ── Батчева класифікація ─────────────────────────────────────
    if total > 0:
        print("[3] Класифікація батчами по", BATCH_SIZE, "...\n")
        start_time = time.time()
        done = 0
        errors = 0

        with driver.session() as session:
            for i in range(0, total, BATCH_SIZE):
                batch = tenders[i : i + BATCH_SIZE]
                texts = [t.get("title") or "без назви" for t in batch]

                try:
                    classified = classify_batch(clf, texts)
                except Exception as e:
                    print(f"\n  ✗ Помилка батча {i//BATCH_SIZE + 1}: {e}")
                    errors += len(batch)
                    done += len(batch)
                    continue

                for t, (category, score, level) in zip(batch, classified):
                    try:
                        session.run(
                            UPDATE_QUERY,
                            tender_id=t["id"],
                            risk_category=category,
                            risk_score=score,
                            risk_level=level,
                        )
                    except Exception as e:
                        print(f"\n  ✗ Neo4j помилка ({t['id']}): {e}")

                done += len(batch)

                # Прогрес
                elapsed = time.time() - start_time
                speed   = done / elapsed if elapsed > 0 else 0
                eta     = (total - done) / speed if speed > 0 else 0
                print(f"\r  {progress_bar(done, total)}  "
                      f"{speed:.1f} т/с  ETA {eta/60:.1f} хв  ",
                      end="", flush=True)

        elapsed_total = time.time() - start_time
        print(f"\n\n  ✓ Класифікацію завершено за {elapsed_total/60:.1f} хв"
              f" (помилок: {errors})\n")

    # ── Фінальний звіт ───────────────────────────────────────────
    print("[4] Підсумковий звіт...\n")
    with driver.session() as session:
        all_results = session.run(GET_ALL_QUERY).data()

    if not all_results:
        print("  ⚠ Немає класифікованих тендерів.")
        driver.close()
        return

    critical = [r for r in all_results if r["score"] >= 0.90]
    medium   = [r for r in all_results if 0.70 <= r["score"] < 0.90]
    low      = [r for r in all_results if r["score"] < 0.70]

    total_budget_risky = sum(
        (r["budget"] or 0) for r in all_results if r["score"] >= 0.70
    )
    total_budget_all   = sum((r["budget"] or 0) for r in all_results)

    print("═" * 70)
    print("  РОЗПОДІЛ РИЗИКІВ")
    print("═" * 70)
    print(f"  🔴 Критичний/Високий (≥0.90) : {len(critical):4} тендерів")
    print(f"  🟠 Середній/Помірний (0.70-0.89): {len(medium):4} тендерів")
    print(f"  🟢 Низький (<0.70)            : {len(low):4} тендерів")
    print(f"  {'─'*50}")
    print(f"  Всього класифіковано          : {len(all_results):4} тендерів")
    print(f"\n  Сума тендерів з ризиком ≥0.70 : {total_budget_risky:>15,.0f} грн")
    print(f"  Загальна сума всіх тендерів   : {total_budget_all:>15,.0f} грн")
    if total_budget_all > 0:
        pct = total_budget_risky / total_budget_all * 100
        print(f"  Частка ризикових              : {pct:>14.1f} %")

    print(f"\n{'═'*70}")
    print("  ТОП-20 НАЙРИЗИКОВАНІШИХ ТЕНДЕРІВ")
    print(f"{'═'*70}")
    print(f"  {'Тендер ID':<28} {'Бюджет (грн)':>14}  {'Рівень':<15} Категорія")
    print(f"  {'─'*95}")
    for r in all_results[:20]:
        tid      = (r["id"] or "")[:27]
        budget   = r["budget"] or 0
        level    = (r["level"] or "")[:14]
        category = (r["category"] or "")[:42]
        print(f"  {tid:<28} {budget:>14,.0f}  {level:<15} {category}")

    print(f"\n{'═'*70}")
    print("  ЗАПИТИ ДЛЯ NEO4J BROWSER")
    print(f"{'═'*70}")
    print("""
  -- Топ ризиків:
  MATCH (t:Tender) WHERE t.risk_score >= 0.7
  RETURN t.tender_id, t.title, t.budget, t.risk_level, t.risk_category
  ORDER BY t.risk_score DESC, t.budget DESC LIMIT 50

  -- Граф: організація → ризикові тендери:
  MATCH (o:Organization)-[:ANNOUNCED]->(t:Tender)
  WHERE t.risk_score >= 0.9
  RETURN o, t LIMIT 50

  -- Розподіл по категоріях:
  MATCH (t:Tender) WHERE t.risk_category IS NOT NULL
  RETURN t.risk_category AS категорія,
         count(t) AS кількість,
         sum(t.budget) AS загальний_бюджет
  ORDER BY кількість DESC
""")

    driver.close()
    print("✓ Готово!")


if __name__ == "__main__":
    main()
