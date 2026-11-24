import os
import hmac
import streamlit as st
from google import genai

st.set_page_config(
    page_title="MY AI AGENT",
    page_icon="🤖",
    layout="centered",
)

def get_secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return os.getenv(name, default)

APP_PASSWORD = get_secret("APP_PASSWORD")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

st.markdown("""
<style>
    .stApp {max-width: 980px; margin: 0 auto;}
    [data-testid="stChatMessage"] {border-radius: 14px;}
    .hero {padding: 1.2rem 0 .5rem 0;}
    .muted {color: #888; font-size: .92rem;}
</style>
""", unsafe_allow_html=True)

# Private-site access gate: password is configured in the host's Secrets,
# never stored in this source file or displayed in the interface.
if not APP_PASSWORD:
    st.title("🔒 MY AI AGENT — Private access")
    st.error("الموقع مازال ما تهيّأش: خاص المسؤول يضيف APP_PASSWORD فـ Secrets ديال الاستضافة.")
    st.info("منين نربطو الموقع بالاستضافة، غادي نضيفو كلمة السر فالإعدادات السرية ديالها. ما تحطّهاش فهاد الملف.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 MY AI AGENT")
    st.caption("Private AI assistant")
    with st.form("login_form"):
        password = st.text_input("كلمة المرور / Password", type="password")
        submitted = st.form_submit_button("دخول / Sign in", use_container_width=True)
    if submitted:
        if hmac.compare_digest(password, APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("كلمة المرور غير صحيحة.")
    st.stop()

st.markdown('<div class="hero">', unsafe_allow_html=True)
st.title("🤖 MY AI AGENT")
st.caption("مساعدك الذكي — Your personal AI assistant")
st.markdown("</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Settings")
    model = st.selectbox("AI model", ["gemini-3.8-flash"])
    mode = st.selectbox(
        "Assistant mode",
        ["General assistant", "Writing", "Programming", "Study & explanation", "Ideas & content"],
    )
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("Private login is enabled. The AI uses the server-side Gemini key configured in hosting Secrets.")

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

    if not GEMINI_API_KEY:
        warning = "خاص المسؤول يضيف GEMINI_API_KEY فـ Secrets ديال الاستضافة باش يخدم الذكاء الاصطناعي."
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
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    response = client.models.generate_content(
                        model=model,
                        contents=history,
                        config={"system_instruction": system_instruction},
                    )
                    answer = response.text or "ماقدرتش نولد جواب. عاود جرّب."
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    # Show the provider error for troubleshooting, while masking the secret key.
                    safe_error = str(e).replace(GEMINI_API_KEY, "[API KEY HIDDEN]")
                    st.error("وقع مشكل فالربط مع Gemini. تفاصيل الخطأ:")
                    st.code(safe_error[:1500])
