import streamlit as st
import subprocess

st.title("🛡 Антикорупційний Комплаєнс ШІ")
st.subheader("Модуль збору даних з Prozorro")

if st.button("Запустити збір тендерів (Prozorro API)"):
    st.write("Виконується запит...")
    # Запускаємо ваш скрипт v3 через subprocess
    result = subprocess.run(["python", "prozorro_to_neo4j_v3.py"], capture_output=True, text=True)
    
    st.success("Обробку завершено!")
    st.text(result.stdout) # Виведе результат роботи скрипта прямо в браузер

st.divider()
st.subheader("Візуалізація зв'язків")
st.markdown("Перейдіть у [Neo4j Browser](http://localhost:7474/), щоб побачити графи.")