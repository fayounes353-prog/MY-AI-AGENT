import os
import streamlit as st
from google import genai

st.set_page_config(
    page_title="MY AI AGENT",
    page_icon="🤖",
    layout="centered",
)

st.markdown("""
<style>
    .stApp {max-width: 980px; margin: 0 auto;}
    [data-testid="stChatMessage"] {border-radius: 14px;}
    .hero {padding: 1.2rem 0 .5rem 0;}
    .muted {color: #888; font-size: .92rem;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero">', unsafe_allow_html=True)
st.title("🤖 MY AI AGENT")
st.caption("مساعدك الذكي — Your personal AI assistant")
st.markdown("</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input(
        "Gemini API key",
        type="password",
        help="Your key is used only for this session. Do not share it with anyone.",
    )
    model = st.selectbox("AI model", ["gemini-2.5-flash", "gemini-2.0-flash"])
    mode = st.selectbox(
        "Assistant mode",
        ["General assistant", "Writing", "Programming", "Study & explanation", "Ideas & content"],
    )
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("The first version can chat, write, explain and help with code. External actions and automatic web research are not connected yet.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

question = st.chat_input("Write what you want the agent to do...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    key = api_key.strip() or os.getenv("GEMINI_API_KEY", "")
    if not key:
        warning = "باش يخدم الذكاء الاصطناعي، دخل Gemini API key من Settings فالجهة اليسرى. ما تشاركش المفتاح ديالك مع حتى واحد."
        with st.chat_message("assistant"):
            st.warning(warning)
        st.session_state.messages.append({"role": "assistant", "content": warning})
    else:
        system_instruction = (
            "You are MY AI AGENT, a helpful, honest and practical assistant. "
            "Reply in the same language as the user. For Moroccan Darija, use clear Moroccan Darija. "
            f"Current mode: {mode}. Give actionable answers. Never claim you performed an external action "
            "unless a connected tool actually completed it."
        )
        history = []
        for item in st.session_state.messages[:-1]:
            history.append({
                "role": "user" if item["role"] == "user" else "model",
                "parts": [{"text": item["content"]}],
            })
        history.append({"role": "user", "parts": [{"text": question}]})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    client = genai.Client(api_key=key)
                    response = client.models.generate_content(
                        model=model,
                        contents=history,
                        config={"system_instruction": system_instruction},
                    )
                    answer = response.text or "ماقدرتش نولد جواب. عاود جرّب."
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as error:
                    st.error("وقع مشكل فالربط مع Gemini. تأكد من API key أو جرّب من بعد.")
                    st.caption(str(error)[:500])
