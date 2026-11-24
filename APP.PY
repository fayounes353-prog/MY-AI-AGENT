import streamlit as st

st.set_page_config(page_title="My AI Agent", page_icon="🤖")

st.title("🤖 MY AI AGENT")
st.write("Your personal AI assistant")

question = st.text_area("What do you want me to do?")

if st.button("Execute"):
    if question:
        st.write("Your task:", question)
        st.info("AI Agent is ready for the next integration.")
