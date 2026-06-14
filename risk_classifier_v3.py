"""
risk_classifier_v3.py  —  Класифікатор корупційних ризиків (правила)
══════════════════════════════════════════════════════════════════════
ЗМІНА v3: замість NLP-моделі — об'єктивна оцінка за реальними
критеріями: статус тендера + сума + NLP тільки для великих тендерів.

Критерії:
  🔴 КРИТИЧНИЙ  — unsuccessful + бюджет > 500 000
  🔴 ВИСОКИЙ    — complete + бюджет > 1 000 000
  🟠 СЕРЕДНІЙ   — complete 500–1000 тис  АБО unsuccessful ≤ 500 тис
  🟡 ПОМІРНИЙ   — cancelled / active
  🟢 НИЗЬКИЙ    — complete ≤ 500 000

Запуск:
  python risk_classifier_v3.py
"""

from transformers import pipeline
from neo4j import GraphDatabase
import time

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"
TARGET_EDRPOU  = "24604168"

THRESHOLD_HIGH   = 1_000_000
THRESHOLD_MEDIUM =   500_000
NLP_THRESHOLD    =   500_000

GET_TENDERS_QUERY = """
MATCH (o:Organization {edrpou: $edrpou})-[:ANNOUNCED]->(t:Tender)
RETURN t.tender_id AS id, t.title AS title,
       t.budget AS budget, t.status AS status
ORDER BY t.budget DESC
"""

UPDATE_QUERY = """
MATCH (t:Tender {tender_id: $tender_id})
SET t.risk_category = $risk_category,
    t.risk_score    = $risk_score,
    t.risk_level    = $risk_level
"""

NLP_LABELS = [
    "підозрілі або розмиті формулювання предмету закупівлі",
    "чіткий і конкретний предмет закупівлі",
]

def rule_based_risk(status, budget):
    s = (status or "").strip().lower()
    b = float(budget or 0)
    if s == "unsuccessful":
        if b > THRESHOLD_MEDIUM:
            return "неконкурентна закупівля або єдиний постачальник", 0.90, "🔴 КРИТИЧНИЙ"
        return "порушення процедури або строків", 0.70, "🟠 СЕРЕДНІЙ"
    if s == "cancelled":
        return "порушення процедури або строків", 0.60, "🟡 ПОМІРНИЙ"
    if "active" in s:
        return "легітимна закупівля без ознак ризику", 0.40, "🟡 ПОМІРНИЙ"
    if b > THRESHOLD_HIGH:
        return "завищена вартість або нецільове використання коштів", 0.80, "🔴 ВИСОКИЙ"
    if b > THRESHOLD_MEDIUM:
        return "завищена вартість або нецільове використання коштів", 0.55, "🟠 СЕРЕДНІЙ"
    return "легітимна закупівля без ознак ризику", 0.10, "🟢 НИЗЬКИЙ"

def nlp_adjustment(clf, title, base_score):
    if not clf or not title:
        return base_score, ""
    try:
        r = clf(title, candidate_labels=NLP_LABELS,
                hypothesis_template="Цей тендер має: {}.")
        if r["labels"][0] == NLP_LABELS[0]:
            return min(base_score + 0.10, 1.0), " + підозріла назва"
    except Exception:
        pass
    return base_score, ""

def progress(current, total, width=45):
    pct = current / total if total else 0
    bar = "█" * int(width * pct) + "░" * (width - int(width * pct))
    return f"[{bar}] {current}/{total} ({pct*100:.1f}%)"

def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   МОДУЛЬ Б v3 — Класифікатор корупційних ризиків        ║")
    print("╚══════════════════════════════════════════════════════════╝\n")
    print(f"  Пороги: ВИСОКИЙ > {THRESHOLD_HIGH:,} | СЕРЕДНІЙ > {THRESHOLD_MEDIUM:,} грн\n")

    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
    except Exception as e:
        print(f"    ✗ {e}"); return

    print("[1] Завантаження тендерів...")
    with driver.session() as session:
        tenders = session.run(GET_TENDERS_QUERY, edrpou=TARGET_EDRPOU).data()
    print(f"    Знайдено: {len(tenders)}\n")
    if not tenders:
        print("    ⚠ Немає даних."); driver.close(); return

    large = [t for t in tenders if (t.get("budget") or 0) > NLP_THRESHOLD]
    clf = None
    if large:
        print(f"[2] NLP-модель для {len(large)} тендерів > {NLP_THRESHOLD:,} грн...")
        try:
            clf = pipeline("zero-shot-classification",
                           model="joeddav/xlm-roberta-large-xnli")
            print("    ✓ Готова\n")
        except Exception as e:
            print(f"    ⚠ Недоступна ({e}) — тільки правила\n")
    else:
        print("[2] NLP не потрібна\n")

    print("[3] Класифікація...\n")
    start = time.time()
    results = []

    with driver.session() as session:
        for i, t in enumerate(tenders, 1):
            tid    = t.get("id", "")
            title  = t.get("title") or "без назви"
            budget = float(t.get("budget") or 0)
            status = t.get("status") or ""

            category, score, level = rule_based_risk(status, budget)

            note = ""
            if clf and budget > NLP_THRESHOLD:
                score, note = nlp_adjustment(clf, title, score)
                if note and score >= 0.90:
                    level = "🔴 КРИТИЧНИЙ"

            session.run(UPDATE_QUERY, tender_id=tid,
                        risk_category=category,
                        risk_score=round(score, 2),
                        risk_level=level)

            results.append({"id": tid, "title": title, "budget": budget,
                            "status": status, "category": category,
                            "score": score, "level": level, "note": note})

            print(f"\r  {progress(i, len(tenders))}  {(time.time()-start):.0f}с  ",
                  end="", flush=True)

    print(f"\n\n  ✓ Готово за {(time.time()-start):.1f} с\n")

    critical   = [r for r in results if r["score"] >= 0.90]
    high       = [r for r in results if 0.75 <= r["score"] < 0.90]
    medium     = [r for r in results if 0.50 <= r["score"] < 0.75]
    low        = [r for r in results if r["score"] < 0.50]
    total_all  = sum(r["budget"] for r in results)
    total_risky= sum(r["budget"] for r in results if r["score"] >= 0.70)

    print("═" * 65)
    print("  РОЗПОДІЛ РИЗИКІВ")
    print("═" * 65)
    print(f"  🔴 Критичний  (≥0.90)    : {len(critical):4} тендерів")
    print(f"  🔴 Високий    (0.75-0.89): {len(high):4} тендерів")
    print(f"  🟠 Середній   (0.50-0.74): {len(medium):4} тендерів")
    print(f"  🟢 Низький    (<0.50)    : {len(low):4} тендерів")
    print(f"  {'─'*45}")
    print(f"  Всього                   : {len(results):4} тендерів")
    print(f"\n  Сума ризикових (≥0.70)   : {total_risky:>15,.0f} грн")
    print(f"  Загальна сума            : {total_all:>15,.0f} грн")
    if total_all:
        print(f"  Частка ризикових         : {total_risky/total_all*100:>14.1f} %")

    top20 = sorted(results, key=lambda r: (-r["score"], -r["budget"]))[:20]
    print(f"\n{'═'*65}")
    print("  ТОП-20 РИЗИКОВИХ ТЕНДЕРІВ")
    print(f"{'═'*65}")
    for r in top20:
        print(f"  {r['id'][:27]:<28} {r['budget']:>13,.0f}  {r['level']}{r.get('note','')}")
        print(f"    ↳ {r['title'][:70]}")

    unsuccess = sorted([r for r in results if r["status"] == "unsuccessful"],
                       key=lambda x: -x["budget"])
    if unsuccess:
        print(f"\n{'═'*65}")
        print(f"  ТЕНДЕРИ БЕЗ ПЕРЕМОЖЦЯ: {len(unsuccess)} шт")
        print(f"{'═'*65}")
        for r in unsuccess[:10]:
            print(f"  {r['id'][:27]:<28} {r['budget']:>13,.0f} грн")
            print(f"    ↳ {r['title'][:70]}")

    print(f"\n{'═'*65}")
    print("""  NEO4J — перевірка:
  MATCH (t:Tender) WHERE t.risk_score >= 0.75
  RETURN t.tender_id, t.title, t.budget, t.status,
         t.risk_level, t.risk_score
  ORDER BY t.risk_score DESC, t.budget DESC LIMIT 50
""")
    driver.close()
    print("✓ Готово!")

if __name__ == "__main__":
    main()
