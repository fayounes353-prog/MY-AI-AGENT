import os
import hmac
import time
import json
import csv
import io
import re
import subprocess
import tempfile
import urllib.request
import urllib.parse
import streamlit as st
from google import genai
from google.genai import types
from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
import imageio_ffmpeg
import arabic_reshaper
from bidi.algorithm import get_display

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

def rtl(text):
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def find_visual_image(query, temp_dir, index):
    """Find a reusable visual from Wikimedia Commons; fall back cleanly if unavailable."""
    try:
        params = urllib.parse.urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": query + " filetype:bitmap",
            "gsrnamespace": 6,
            "gsrlimit": 8,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": 1200,
            "format": "json"
        })
        req = urllib.request.Request(
            "https://commons.wikimedia.org/w/api.php?" + params,
            headers={"User-Agent": "MYAIAgentVideoStudio/1.0 (educational video creator)"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pages = list(payload.get("query", {}).get("pages", {}).values())
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            image_req = urllib.request.Request(
                url, headers={"User-Agent": "MYAIAgentVideoStudio/1.0"}
            )
            with urllib.request.urlopen(image_req, timeout=20) as image_response:
                raw = image_response.read()
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((1400, 2200))
            path = os.path.join(temp_dir, f"visual_{index:02d}.jpg")
            image.save(path, quality=90)
            return path
    except Exception:
        pass
    return None


def make_video_slide(title, paragraph, output_path, index, total, image_path=None):
    width, height = 1080, 1920
    if image_path:
        try:
            source = Image.open(image_path).convert("RGB")
            sw, sh = source.size
            scale = max(width / sw, height / sh)
            source = source.resize((int(sw * scale), int(sh * scale)), Image.Resampling.LANCZOS)
            left = (source.width - width) // 2
            top = (source.height - height) // 2
            img = source.crop((left, top, left + width, top + height))
            shade = Image.new("RGBA", (width, height), (3, 12, 28, 155))
            img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
        except Exception:
            img = Image.new("RGB", (width, height), (8, 19, 39))
    else:
        img = Image.new("RGB", (width, height), (8, 19, 39))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 34), fill=(220, 38, 48))
    draw.rectangle((70, 150, 1010, 154), fill=(220, 38, 48))
    try:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        title_font = ImageFont.truetype(font_path, 66)
        body_font = ImageFont.truetype(font_path, 54)
        small_font = ImageFont.truetype(font_path, 34)
    except Exception:
        title_font = body_font = small_font = ImageFont.load_default()

    draw.text((width-75, 95), rtl("CHNO WA9E3"), font=title_font, fill=(255,255,255), anchor="ra")
    draw.text((width-75, 220), rtl("الحقيقة قبل العنوان"), font=small_font, fill=(255,105,105), anchor="ra")
    draw.rounded_rectangle((55, 390, 1025, 1510), radius=36, fill=(5, 16, 34), outline=(220,38,48), width=3)

    words = paragraph.split()
    lines, current = [], ""
    max_width = 840
    for word in words:
        candidate = (current + " " + word).strip()
        shaped = rtl(candidate)
        if draw.textbbox((0,0), shaped, font=body_font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    line_height = 82
    max_lines = 10
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + "…"
    block_height = len(lines) * line_height
    y = 945 - block_height // 2
    for line in lines:
        draw.text((950, y), rtl(line), font=body_font, fill=(255,255,255), anchor="ra")
        y += line_height

    draw.text((width-75, 1630), rtl(title[:55]), font=small_font, fill=(225,235,248), anchor="ra")
    draw.rectangle((70, 1760, 1010, 1770), fill=(65,80,105))
    progress_w = int(940 * (index+1) / max(total,1))
    draw.rectangle((70, 1760, 70+progress_w, 1770), fill=(220,38,48))
    draw.text((width//2, 1825), rtl(f"المشهد {index+1} / {total}"), font=small_font, fill=(220,230,245), anchor="mm")
    img.save(output_path, quality=92)


def research_and_write_script(topic, api_key, model):
    """Use web-grounded Gemini research to draft a short Arabic news video script."""
    client = genai.Client(api_key=api_key)
    prompt = (
        "ابحث في الويب عن آخر المعلومات الموثوقة حول الموضوع التالي: " + topic + "\\n"
        "اكتب سيناريو فيديو عربي قصير لقناة CHNO WA9E3 مدته 45 إلى 60 ثانية. "
        "استعمل معلومات حديثة فقط إذا وجدت مصادر موثوقة، وميّز بين المؤكد وغير المؤكد. "
        "لا تخترع أرقاما أو تصريحات. ابدأ بعنوان جذاب ثم 5 إلى 7 جمل قصيرة مناسبة للتعليق الصوتي. "
        "في النهاية أضف فقرة بعنوان المصادر تتضمن روابط أو أسماء المصادر التي اعتمدت عليها. "
        "لا تنقل نصوصا محمية ولا تعِد نشر فيديوهات الآخرين."
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "system_instruction": "أنت محرر أخبار دقيق. تحقق من الوقائع واستعمل البحث في الويب.",
            "tools": [types.Tool(google_search=types.GoogleSearch())],
        },
    )
    return response.text or "لم يتم إنشاء السيناريو. حاول مرة أخرى."


def build_vertical_video(title, script, language="ar"):
    paragraphs = [p.strip() for p in re.split(r"(?<=[.!؟])\s+|\n+", script) if p.strip()]
    if not paragraphs:
        paragraphs = [script.strip()]
    scenes = []
    for p in paragraphs:
        while len(p) > 260:
            cut = p.rfind(" ", 0, 240)
            if cut < 80:
                cut = 240
            scenes.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            scenes.append(p)
    scenes = scenes[:8]
    if not scenes:
        raise ValueError("كتب نص الفيديو أولا.")

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = os.path.join(temp_dir, "voice.mp3")
        tts = gTTS(text=script, lang=language, slow=False)
        tts.save(audio_path)

        concat_path = os.path.join(temp_dir, "slides.txt")
        slide_paths = []
        durations = [max(4.0, len(s) / 6.0 + 2.0) for s in scenes]
        for i, scene in enumerate(scenes):
            # Search for a related freely reusable visual on Wikimedia Commons.
            visual_query = " ".join(scene.split()[:7])
            visual_path = find_visual_image(visual_query, temp_dir, i)
            slide_path = os.path.join(temp_dir, f"slide_{i:02d}.jpg")
            make_video_slide(title, scene, slide_path, i, len(scenes), visual_path)
            slide_paths.append(slide_path)

        with open(concat_path, "w", encoding="utf-8") as listing:
            for i, slide_path in enumerate(slide_paths):
                listing.write(f"file '{slide_path}'\n")
                listing.write(f"duration {durations[i]:.2f}\n")
            listing.write(f"file '{slide_paths[-1]}'\n")

        output_path = os.path.join(temp_dir, "chno_wa9e3_video.mp4")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
            "-i", audio_path,
            "-vf", "zoompan=z='min(zoom+0.00035,1.07)':d=1:s=1080x1920:fps=24,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-r", "24",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "FFmpeg error")[-1800:])
        with open(output_path, "rb") as video_file:
            return video_file.read()

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
st.caption("مساعدك الذكي — كيساعدك تنجز المهام، يحلل الملفات ويصاوب الفيديوهات")
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

st.subheader("🎬 CHNO WA9E3 — Video Studio")
st.caption("دخل موضوعاً، والوكيل يبحث في الويب ويكتب سيناريو، ثم يصنع فيديو عمودياً بصوت عربي وصور متاحة لإعادة الاستخدام.")
topic = st.text_input("شنو الموضوع اللي نقلب عليه؟", placeholder="مثال: آخر تطورات كأس العالم 2030")
if st.button("🔎 بحث وكتابة السيناريو", use_container_width=True):
    if not topic.strip():
        st.warning("كتب موضوع البحث أولا.")
    elif not GEMINI_API_KEY:
        st.error("البحث في الويب يحتاج GEMINI_API_KEY محفوظاً في Secrets.")
    else:
        try:
            with st.spinner("كنقلب فالويب وكنحضّر سيناريو بالمصادر..."):
                draft = research_and_write_script(topic.strip(), GEMINI_API_KEY, "gemini-3.5-flash-lite")
            st.session_state["video_research_draft"] = draft
            st.session_state["video_topic"] = topic.strip()
        except Exception as e:
            st.error("تعذر البحث أو كتابة السيناريو حالياً.")
            st.code(str(e).replace(GEMINI_API_KEY, "[API KEY HIDDEN]")[:1400])

video_title = st.text_input("عنوان الفيديو", value=st.session_state.get("video_topic", "أهم أخبار اليوم"))
video_script = st.text_area(
    "راجع السيناريو أو عدّله قبل الإنتاج",
    value=st.session_state.get("video_research_draft", ""),
    height=240,
    placeholder="من بعد البحث، غادي يظهر هنا السيناريو مع المصادر..."
)
if st.button("🎥 صايب الفيديو", type="primary", use_container_width=True):
    if len(video_script.strip()) < 40:
        st.warning("خاص السيناريو يكون فيه على الأقل 40 حرف.")
    else:
        try:
            with st.spinner("كنصاوب الفيديو والصوت والصور... خليه مفتوح حتى يسالي"):
                video_bytes = build_vertical_video(video_title.strip() or "CHNO WA9E3", video_script.strip())
            st.session_state["generated_video"] = video_bytes
            st.success("الفيديو واجد!")
        except Exception as e:
            st.error("ما قدرناش نصاوبو الفيديو هاد المرة.")
            st.code(str(e)[:1800])
if st.session_state.get("generated_video"):
    st.video(st.session_state["generated_video"])
    st.download_button(
        "⬇️ حمّل الفيديو MP4",
        data=st.session_state["generated_video"],
        file_name="CHNO_WA9E3_video.mp4",
        mime="video/mp4",
        use_container_width=True
    )
st.caption("هاد النسخة كتنتج فيديو من النص بصوت آلي وتصميم CHNO WA9E3. النشر التلقائي للحسابات غادي نربطوه فمرحلة لاحقة.")

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
            "performed actions outside this app unless a connected tool actually completed it. "
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
