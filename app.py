import os
import hmac
import time
import json
import urllib.request
import streamlit as st
from google import genai
from google.genai import types

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
GROQ_API_KEY = get_secret("GROQ_API_KEY")

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
    provider = st.selectbox("AI provider", ["Gemini", "Groq (free alternative)"])
    if provider == "Gemini":
        model = st.selectbox("AI model", ["gemini-3.5-flash-lite", "gemini-3.8-flash"])
    else:
        model = st.selectbox("AI model", ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
    mode = st.selectbox(
        "Assistant mode",
        ["General assistant", "Writing", "Programming", "Study & explanation", "Ideas & content"],
    )
    if provider == "Gemini":
        web_search = st.checkbox("البحث في الإنترنت (Google)", value=False)
    else:
        web_search = False
        st.caption("البحث المباشر غير متاح حالياً مع Groq.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("Private login is enabled. API keys stay private in hosting Secrets.")

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

    active_key = GEMINI_API_KEY if provider == "Gemini" else GROQ_API_KEY
    if not active_key:
        secret_name = "GEMINI_API_KEY" if provider == "Gemini" else "GROQ_API_KEY"
        warning = f"خاص تزيد {secret_name} فـ Secrets ديال الاستضافة باش يخدم هاد المزوّد."
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
                    if provider == "Gemini":
                        client = genai.Client(api_key=GEMINI_API_KEY)
                        response = None
                        last_error = None
                        for attempt in range(3):
                            try:
                                request_config = {"system_instruction": system_instruction}
                                if web_search:
                                    request_config["tools"] = [
                                        types.Tool(google_search=types.GoogleSearch())
                                    ]
                                response = client.models.generate_content(
                                    model=model,
                                    contents=history,
                                    config=request_config,
                                )
                                break
                            except Exception as e:
                                last_error = e
                                if "503" in str(e) and attempt < 2:
                                    time.sleep(2 ** (attempt + 1))
                                    continue
                                raise
                        if response is None and last_error is not None:
                            raise last_error
                        answer = response.text or "ماقدرتش نولد جواب. عاود جرّب."
                    else:
                        messages = [{"role": "system", "content": system_instruction}]
                        for item in st.session_state.messages:
                            messages.append({
                                "role": "assistant" if item["role"] == "assistant" else "user",
                                "content": item["content"],
                            })
                        payload = json.dumps({
                            "model": model,
                            "messages": messages,
                            "temperature": 0.7,
                            "max_tokens": 2048,
                        }).encode("utf-8")
                        req = urllib.request.Request(
                            "https://api.groq.com/openai/v1/chat/completions",
                            data=payload,
                            headers={
                                "Authorization": f"Bearer {GROQ_API_KEY}",
                                "Content-Type": "application/json",
                            },
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        answer = data["choices"][0]["message"]["content"] or "ماقدرتش نولد جواب. عاود جرّب."
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    safe_error = str(e).replace(GEMINI_API_KEY, "[API KEY HIDDEN]")
                    safe_error = safe_error.replace(GROQ_API_KEY, "[API KEY HIDDEN]")
                    st.error(f"وقع مشكل فالربط مع {provider}. تفاصيل الخطأ:")
                    st.code(safe_error[:1500])
