import os
import hmac
import time
import json
import csv
import io
import urllib.request
import streamlit as st
from google import genai
from google.genai import types
from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook

st.set_page_config(page_title="MY AI AGENT", page_icon="🤖", layout="centered")

def get_secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return os.getenv(name, default)

def extract_file(uploaded):
    name = uploaded.name
    raw = uploaded.getvalue()
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("txt", "md", "csv", "json", "py", "html", "xml", "log"):
        return raw.decode("utf-8", errors="replace")
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == "docx":
        doc = Document(io.BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs)
    if ext == "xlsx":
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        chunks = []
        for sheet in book.worksheets:
            chunks.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                chunks.append(" | ".join("" if v is None else str(v) for v in row))
        return "\n".join(chunks)
    raise ValueError("نوع الملف غير مدعوم. استعمل PDF أو DOCX أو XLSX أو TXT أو CSV أو MD.")

APP_PASSWORD = get_secret("APP_PASSWORD")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")

st.markdown("""
<style>
.stApp {max-width: 980px; margin: 0 auto;}
[data-testid="stChatMessage"] {border-radius: 14px;}
.hero {padding: 1.2rem 0 .5rem 0;}
</style>
""", unsafe_allow_html=True)

if not APP_PASSWORD:
    st.title("🔒 MY AI AGENT — Private access")
    st.error("خاص المسؤول يضيف APP_PASSWORD فـ Secrets ديال الاستضافة.")
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
st.caption("مساعدك الذكي — كيساعدك تنجز المهام، يحلل الملفات ويكتب المحتوى")
st.markdown("</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Settings")
    provider = st.selectbox("AI provider", ["Gemini", "OpenRouter (free models)"])
    if provider == "Gemini":
        model = st.selectbox("AI model", ["gemini-3.5-flash-lite", "gemini-3.8-flash"])
        web_search = st.checkbox("البحث في الإنترنت (Google)", value=False)
    else:
        model = "openrouter/free"
        web_search = False
        st.caption("البحث المباشر متاح حالياً مع Gemini فقط.")
    mode = st.selectbox("Assistant mode", [
        "General assistant", "Writing", "Programming",
        "Study & explanation", "Ideas & content", "Business & accounting"
    ])
    st.divider()
    st.subheader("📎 File analysis")
    uploaded_files = st.file_uploader(
        "حمّل ملفات باش نحللها",
        type=["pdf", "docx", "xlsx", "txt", "csv", "md", "json", "py"],
        accept_multiple_files=True,
        help="يمكن تحميل PDF وWord وExcel وTXT وCSV وMarkdown."
    )
    if uploaded_files:
        st.caption(f"{len(uploaded_files)} ملف/ملفات جاهزة للتحليل.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("مفاتيح API محفوظة بشكل سري في Streamlit Secrets.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.messages:
    last_assistant = next((m["content"] for m in reversed(st.session_state.messages) if m["role"] == "assistant"), None)
    if last_assistant:
        st.download_button("⬇️ Télécharger آخر جواب", data=last_assistant, file_name="my-ai-agent-answer.txt", mime="text/plain")

question = st.chat_input("كتب المهمة اللي بغيتي الوكيل ينجزها...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    attachment_context = ""
    if uploaded_files:
        parts = []
        for uploaded in uploaded_files:
            try:
                extracted = extract_file(uploaded)
                parts.append(f"\n--- FILE: {uploaded.name} ---\n{extracted[:30000]}")
            except Exception as e:
                parts.append(f"\n--- FILE: {uploaded.name} ---\nتعذر قراءة الملف: {e}")
        attachment_context = "\n\nمحتوى الملفات المرفقة (استعمله للإجابة على طلب المستخدم):\n" + "\n".join(parts)

    user_prompt = question + attachment_context
    active_key = GEMINI_API_KEY if provider == "Gemini" else OPENROUTER_API_KEY
    if not active_key:
        secret_name = "GEMINI_API_KEY" if provider == "Gemini" else "OPENROUTER_API_KEY"
        warning = f"خاص تزيد {secret_name} فـ Secrets ديال الاستضافة."
        with st.chat_message("assistant"):
            st.warning(warning)
        st.session_state.messages.append({"role": "assistant", "content": warning})
    else:
        system_instruction = (
            "You are MY AI AGENT, a practical task assistant. Reply in the user's language; "
            "for Moroccan Darija, use clear Moroccan Darija. Current mode: " + mode + ". "
            "When asked to perform a task, do the work in your answer: draft the complete text, "
            "analyze provided data, produce code, calculations, plans, or structured results. "
            "For attached files, rely on their contents and mention if extraction appears incomplete. "
            "Be honest: never claim to have sent messages, changed accounts, made purchases, or "
            "performed actions outside this app unless a connected tool actually completed them. "
            "Ask for confirmation before any consequential external action."
        )
        history = []
        for item in st.session_state.messages[:-1]:
            history.append({
                "role": "user" if item["role"] == "user" else "model",
                "parts": [{"text": item["content"]}],
            })
        history.append({"role": "user", "parts": [{"text": user_prompt}]})

        with st.chat_message("assistant"):
            with st.spinner("الوكيل كينفذ المهمة..."):
                try:
                    if provider == "Gemini":
                        client = genai.Client(api_key=GEMINI_API_KEY)
                        response = None
                        last_error = None
                        for attempt in range(3):
                            try:
                                request_config = {"system_instruction": system_instruction}
                                if web_search:
                                    request_config["tools"] = [types.Tool(google_search=types.GoogleSearch())]
                                response = client.models.generate_content(
                                    model=model, contents=history, config=request_config
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
                        for item in st.session_state.messages[:-1]:
                            messages.append({
                                "role": "assistant" if item["role"] == "assistant" else "user",
                                "content": item["content"],
                            })
                        messages.append({"role": "user", "content": user_prompt})
                        payload = json.dumps({
                            "model": model, "messages": messages,
                            "temperature": 0.7, "max_tokens": 3000,
                        }).encode("utf-8")
                        req = urllib.request.Request(
                            "https://openrouter.ai/api/v1/chat/completions",
                            data=payload,
                            headers={
                                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "https://my-ai-agent.streamlit.app",
                                "X-Title": "MY AI AGENT",
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
                    safe_error = safe_error.replace(OPENROUTER_API_KEY, "[API KEY HIDDEN]")
                    st.error(f"وقع مشكل فالربط مع {provider}.")
                    st.code(safe_error[:1500])
