"""
dashboard_viewer.py — Мінімальна панель перегляду результатів ProRiskGraph
══════════════════════════════════════════════════════════════════════
Що робить:
  Тільки ЧИТАЄ й показує дані, вже записані в Neo4j попередніми
  скриптами (prozorro_to_neo4j_v8.py, risk_classifier_v3.py тощо).
  Нічого не запускає, нічого не обробляє — жодних важких залежностей
  (transformers, torch, OCR тут немає), тому шанс на робочий запуск
  набагато вищий, ніж у попередньої версії.

Встановити один раз (окрім вже встановлених neo4j):
  pip install streamlit pandas

Запуск:
  streamlit run dashboard_viewer.py
  (браузер сам відкриє http://localhost:8501)
"""

import streamlit as st
import pandas as pd
from neo4j import GraphDatabase

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

st.set_page_config(page_title="ProRiskGraph", layout="wide")
st.title("ProRiskGraph — панель перегляду результатів")

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

driver = get_driver()

# ─── Перевірка підключення ────────────────────────────────────────────
try:
    driver.verify_connectivity()
    st.success("Підключено до Neo4j")
except Exception as e:
    st.error(f"Не вдалося підключитися до Neo4j: {e}")
    st.stop()

# ─── Загальна статистика ───────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with driver.session() as session:
    total_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    total_rels  = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    total_tenders = session.run(
        "MATCH (t) WHERE t:Tender OR t:LowRisk OR t:MediumRisk OR t:HighRisk "
        "RETURN count(t) AS c"
    ).single()["c"]

col1.metric("Вузлів у графі", total_nodes)
col2.metric("Зв'язків у графі", total_rels)
col3.metric("Тендерів у базі", total_tenders)

st.divider()

# ─── Таблиця ризикових тендерів ────────────────────────────────────────
st.subheader("Тендери з ризиком ≥ 0.70")

QUERY_RISKY = """
MATCH (t)
WHERE (t:Tender OR t:LowRisk OR t:MediumRisk OR t:HighRisk)
  AND t.risk_score >= 0.70
RETURN t.tender_id AS tender_id, t.title AS title,
       t.budget AS budget, t.risk_level AS risk_level,
       t.risk_score AS risk_score
ORDER BY t.risk_score DESC, t.budget DESC
LIMIT 50
"""

with driver.session() as session:
    rows = session.run(QUERY_RISKY).data()

if rows:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
else:
    st.info("Немає тендерів з risk_score ≥ 0.70 у поточній базі.")

st.divider()

# ─── Конфлікт інтересів (збіг адрес) ───────────────────────────────────
st.subheader("Виявлені збіги адрес (конфлікт інтересів)")

QUERY_CONFLICTS = """
MATCH (o:Officer)-[:REGISTERED_AT]->(a:Address)<-[:HAS_HQ_AT]-(c:Company)
RETURN o.name AS officer, c.name AS company, a.full_address AS address
"""

with driver.session() as session:
    conflict_rows = session.run(QUERY_CONFLICTS).data()

if conflict_rows:
    st.dataframe(pd.DataFrame(conflict_rows), use_container_width=True)
else:
    st.info("Збігів адрес у поточній базі не знайдено.")

st.caption("Дані оновлюються скриптами Модуля А та Модуля Б. "
           "Ця панель лише відображає вже записані результати.")
