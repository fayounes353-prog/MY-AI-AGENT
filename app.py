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
import xml.etree.ElementTree as ET
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


def search_reusable_video_clips(query, limit=8):
    """Search Wikimedia Commons for video files and return source/license metadata."""
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query + " filetype:video",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 640,
        "format": "json"
    })
    request = urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?" + params,
        headers={"User-Agent": "MYAIAgentVideoStudio/1.0 (video research assistant)"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results = []
    for page in payload.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        file_url = info.get("url", "")
        extension = os.path.splitext(urllib.parse.urlparse(file_url).path)[1].lower()
        if extension not in (".webm", ".ogv", ".ogg", ".mp4", ".mpeg", ".mpg"):
            continue
        metadata = info.get("extmetadata") or {}
        def metadata_value(key):
            value = metadata.get(key, {}).get("value", "")
            return re.sub(r"<[^>]+>", "", str(value)).strip()
        results.append({
            "title": page.get("title", "Video"),
            "url": file_url,
            "page": info.get("descriptionurl", ""),
            "license": metadata_value("LicenseShortName") or metadata_value("UsageTerms") or "راجع صفحة الملف",
            "artist": metadata_value("Artist") or "غير محدد",
            "credit": metadata_value("Credit")
        })
    return results



def search_anything_rss(query):
    """Fallback web search using public Google News RSS, without requiring an AI API key."""
    results = []
    for lang, gl, ceid in [("en", "US", "US:en"), ("ar", "MA", "MA:ar")]:
        params = urllib.parse.urlencode({
            "q": query, "hl": lang, "gl": gl, "ceid": ceid
        })
        url = "https://news.google.com/rss/search?" + params
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 MYAIAgent/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=18) as response:
                root = ET.fromstring(response.read())
            for item in root.findall(".//item")[:10]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pubdate = (item.findtext("pubDate") or "").strip()
                if title and link and all(x["link"] != link for x in results):
                    results.append({"title": title, "link": link, "date": pubdate})
        except Exception:
            continue
    if not results:
        raise RuntimeError("ما قدرناش نوصلو حتى لمصدر بحث. تحقق من اتصال التطبيق بالإنترنت.")
    lines = ["### نتائج البحث المباشر", "لقيت هاد النتائج المنشورة، راجع الروابط للتفاصيل:"]
    for item in results[:15]:
        lines.append(f"- [{item['title']}]({item['link']}) — {item['date']}")
    lines.append("\nملاحظة: هادي نتائج RSS إخبارية؛ البحث العام الشامل كيتطلب Gemini Search.")
    return "\n".join(lines)


def search_anything_on_web(query, api_key=""):
    """Try grounded Gemini search; fall back to RSS when Gemini is unavailable or quota-limited."""
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "ابحث في الإنترنت بحثاً واسعاً عن هذا الطلب: " + query + "\n"
                "استعمل Google Search للعثور على صفحات ومصادر حقيقية وحديثة. "
                "إذا كان الموضوع لعبة أو فيلم أو فيديو، ابحث كذلك عن المقطع الرسمي، "
                "الموقع الرسمي، الأخبار، والمصادر المفيدة. "
                "أجب بلغة المستخدم، وقدم خلاصة واضحة ثم روابط المصادر التي عثرت عليها. "
                "فرّق بين المعلومة المؤكدة والإشاعة، ولا تخترع روابط أو نتائج."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "system_instruction": "أنت وكيل بحث على الإنترنت. ابحث قبل الإجابة، واستشهد بمصادر وروابط حقيقية.",
                    "tools": [types.Tool(google_search=types.GoogleSearch())],
                },
            )
            if response.text and response.text.strip():
                return response.text.strip()
        except Exception as gemini_error:
            fallback = search_anything_rss(query)
            return fallback + "\n\nملاحظة تقنية: تعذر البحث الذكي مؤقتاً، لذلك استعملت البحث الإخباري المباشر."
    return search_anything_rss(query)


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


def fetch_news_rss(topic):
    """Return recent Google News RSS items with their source links."""
    query = urllib.parse.quote(topic + " Morocco OR العالم")
    rss_url = "https://news.google.com/rss/search?q=" + query + "&hl=ar&gl=MA&ceid=MA:ar"
    req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0 MYAIAgent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        xml_data = response.read()
    root = ET.fromstring(xml_data)
    items = []
    for item in root.findall(".//item")[:12]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pubdate = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "date": pubdate})
    return items


def research_with_openrouter_rss(topic, api_key):
    """Use OpenRouter to draft from RSS; if its free route returns no text, build a cautious headline-only bulletin."""
    items = fetch_news_rss(topic)
    if not items:
        raise RuntimeError("ما لقيتش عناوين إخبارية فـ Google News RSS.")
    prompt = (
        "أنشئ سيناريو فيديو عربي لقناة CHNO WA9E3 مدته 45 إلى 60 ثانية. "
        "استعمل العناوين التالية فقط ولا تخترع تفاصيل أو أرقاما. "
        "اكتب عنوانا ثم 5 إلى 7 جمل قصيرة للتعليق الصوتي ثم فقرة المصادر بالروابط. "
        "إذا كان العنوان وحده لا يكفي لتأكيد التفاصيل، قل: حسب العنوان المنشور. "
        "لا تضع المصادر داخل التعليق الصوتي.\n\n"
        + "\n".join(f"- {x['title']} | {x['date']} | {x['link']}" for x in items)
    )
    payload = json.dumps({
        "model": "openrouter/free",
        "messages": [
            {"role": "system", "content": "أنت محرر أخبار دقيق. لا تخترع أي معلومة."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 2200
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://my-ai-agent.streamlit.app",
            "X-Title": "CHNO WA9E3 Video Studio"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") in ("text", "output_text")
            )
        if isinstance(content, str) and len(content.strip()) >= 40:
            return content.strip()
    except Exception:
        # RSS fallback below still permits a sourced headline-only video.
        pass

    # Deterministic fallback: narrate only the published headlines, never invented context.
    selected = items[:6]
    lines = [
        "عنوان: موجز آخر الأخبار حسب العناوين المنشورة",
        "هذا موجز إخباري مبني على عناوين وروابط منشورة في Google News.",
    ]
    for item in selected:
        lines.append("حسب العنوان المنشور، " + item["title"].rstrip(" .،؛") + ".")
    lines.append("هذا الموجز يقتصر على ما ورد في العناوين، والتفاصيل الكاملة موجودة في المصادر.")
    lines.append("المصادر:")
    lines.extend(f"- {item['title']} — {item['link']}" for item in selected)
    return "\n".join(lines)


def research_and_write_script(topic, api_key, model):
    """Use web-grounded Gemini research to draft a short Arabic news video script."""
    client = genai.Client(api_key=api_key)
    prompt = (
        "ابحث في الويب عن آخر المعلومات الموثوقة حول الموضوع التالي: " + topic + "\n"
        "اكتب سيناريو فيديو عربي قصير لقناة CHNO WA9E3 مدته 45 إلى 60 ثانية. "
        "استعمل معلومات حديثة فقط إذا وجدت مصادر موثوقة، وميّز بين المؤكد وغير المؤكد. "
        "رتّب الإجابة هكذا: سطر أول يبدأ بعنوان: ثم عنوان قصير؛ بعده نص التعليق الصوتي في 5 إلى 7 جمل قصيرة؛ "
        "ثم فقرة مستقلة بعنوان المصادر تحتوي روابط أو أسماء المصادر. "
        "لا تخترع أرقاما أو تصريحات، ولا تضع المصادر داخل نص التعليق الصوتي. "
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
    # Keep sources in the review panel, but never read them aloud.
    narration = re.split(r"(?im)^\s*(?:المصادر|المراجع|sources|references)\s*[:：]?.*$", script)[0].strip()
    narration = re.sub(r"(?im)^\s*(?:عنوان الفيديو|العنوان|عنوان|headline)\s*[:：]\s*", "", narration)
    narration = re.sub(r"(?m)^\s*#+\s*", "", narration)
    narration = re.sub(r"[*_`]", "", narration).strip()
    paragraphs = [p.strip(" -•\t") for p in re.split(r"(?<=[.!؟])\s+|\n+", narration) if p.strip(" -•\t")]
    if not paragraphs:
        raise ValueError("ما لقيتش نص التعليق الصوتي قبل فقرة المصادر. عاود إنشاء السيناريو.")
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
        tts = gTTS(text=" ".join(paragraphs), lang=language, slow=False)
        tts.save(audio_path)

        concat_path = os.path.join(temp_dir, "slides.txt")
        slide_paths = []
        # Measure the generated narration so scene captions stay on screen for the full voiceover.
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        probe = subprocess.run(
            [ffmpeg, "-i", audio_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=60
        )
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
        if duration_match:
            hh, mm, ss = duration_match.groups()
            audio_duration = int(hh) * 3600 + int(mm) * 60 + float(ss)
        else:
            audio_duration = max(12.0, sum(len(s) for s in scenes) / 11.0)
        weights = [max(1, len(s)) for s in scenes]
        total_weight = sum(weights)
        durations = [max(2.5, audio_duration * w / total_weight) for w in weights]
        # Keep the slideshow slightly longer than the narration to avoid cutting the last words.
        durations[-1] += 1.0
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
            "-vf", "zoompan=z='min(zoom+0.00035,1.07)':d=1:s=1080x1920:fps=30,scale=1080:1920:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
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

st.subheader("🌐 Universal Search Agent — قلب فكل الإنترنت")
st.caption("كتب أي موضوع: لعبة، فيلم، خبر، منتوج، شخص، فيديو... والوكيل غادي يبحث فالويب باستعمال Google Search، ويعطيك روابط مباشرة لمصادر أخرى.")
with st.form("universal_search_form"):
    universal_query = st.text_input("شنو بغيتي نلقى؟", placeholder="مثلاً: GTA 6 gameplay trailer release date")
    universal_submit = st.form_submit_button("🌍 قلب فكلشي", use_container_width=True)
if universal_submit:
    if not universal_query.strip():
        st.warning("كتب شنو كتقلب عليه.")
    elif not GEMINI_API_KEY:
        st.error("خاص GEMINI_API_KEY يكون محفوظ فـ Streamlit Secrets باش نخدم البحث الذكي.")
    else:
        try:
            with st.spinner("الوكيل كيقلب فالويب وكيجمع المعلومات والروابط..."):
                universal_result = search_anything_on_web(universal_query.strip(), GEMINI_API_KEY)
                st.session_state["universal_search_result"] = universal_result
                st.session_state["universal_search_query"] = universal_query.strip()
        except Exception as search_error:
            st.error("البحث ما كملش. جرّب مرة أخرى.")
            st.caption("تفاصيل الخطأ: " + str(search_error)[:700])

if st.session_state.get("universal_search_result"):
    st.markdown("### نتائج البحث: " + st.session_state.get("universal_search_query", ""))
    st.markdown(st.session_state["universal_search_result"])
    q_encoded = urllib.parse.quote_plus(st.session_state.get("universal_search_query", ""))
    st.markdown("**زيد قلب مباشرة فمواقع أخرى:**")
    st.markdown(
        f"[Google](https://www.google.com/search?q={q_encoded}) · "
        f"[Google Videos](https://www.google.com/search?tbm=vid&q={q_encoded}) · "
        f"[YouTube](https://www.youtube.com/results?search_query={q_encoded}) · "
        f"[Internet Archive](https://archive.org/search?query={q_encoded}) · "
        f"[Wikimedia Commons](https://commons.wikimedia.org/w/index.php?search={q_encoded})"
    )

st.subheader("🎞️ Video Search Agent — البحث عن مقاطع فيديو")
st.caption("كيقلب فـ Wikimedia Commons على مقاطع فيديو قابلة لإعادة الاستخدام، وكيعرض المصدر والترخيص باش تراجع الشروط قبل النشر.")
with st.form("video_search_form"):
    clip_query = st.text_input("شنو نوع الفيديو اللي كتقلب عليه؟", placeholder="مثلاً: Casablanca street, ocean waves, football stadium")
    search_submitted = st.form_submit_button("🔎 قلب على فيديوهات", use_container_width=True)
if search_submitted:
    if not clip_query.strip():
        st.warning("كتب موضوع البحث أولاً.")
    else:
        try:
            with st.spinner("Agent البحث كيقلب على مقاطع مناسبة..."):
                st.session_state["video_clip_results"] = search_reusable_video_clips(clip_query.strip())
                st.session_state["video_clip_query"] = clip_query.strip()
        except Exception as search_error:
            st.error("ما قدرش Agent البحث يوصل للمكتبة دابا.")
            st.caption(str(search_error)[:500])

if "video_clip_results" in st.session_state:
    clip_results = st.session_state["video_clip_results"]
    st.caption(f"نتائج البحث عن: {st.session_state.get('video_clip_query', '')} — {len(clip_results)} مقطع")
    if not clip_results:
        st.info("ما تلقاو حتى مقاطع فيديو مطابقة. جرّب كلمات بحث بالإنجليزية.")
    for clip_index, clip in enumerate(clip_results):
        with st.expander(f"🎬 {clip['title']}"):
            st.write("الترخيص:", clip["license"])
            st.write("صاحب العمل / النسبة:", clip["artist"])
            if clip["page"]:
                st.markdown(f"[فتح صفحة المصدر ومراجعة شروط الاستعمال]({clip['page']})")
            st.markdown(f"[فتح ملف الفيديو الأصلي]({clip['url']})")
            if clip_index < 3:
                st.video(clip["url"])

st.subheader("🎬 CHNO WA9E3 — Video Studio")
st.caption("الوكيل يختار موضوعاً إخبارياً عاماً، يبحث عنه، يكتب السيناريو ويصنع الفيديو بالصوت والصور في خطوة واحدة.")
auto_topic = st.text_input(
    "المجال (اختياري)",
    value=st.session_state.get("auto_video_topic", "آخر أخبار المغرب والعالم"),
    help="تقدر تخليه كما هو أو تكتب مجالاً بحال التكنولوجيا أو الرياضة."
)
if st.button("🤖 صايب ليا فيديو جديد بوحدك", type="primary", use_container_width=True):
    if not GEMINI_API_KEY:
        st.error("خاص GEMINI_API_KEY يبقى محفوظاً فـ Secrets.")
    elif not auto_topic.strip():
        st.warning("كتب المجال اللي بغيتي.")
    else:
        try:
            with st.spinner("1/2 كنقلب على الأخبار وكنكتب السيناريو..."):
                try:
                    draft = research_and_write_script(
                        auto_topic.strip(), GEMINI_API_KEY, "gemini-3.5-flash-lite"
                    )
                except Exception as gemini_error:
                    if "429" not in str(gemini_error) and "RESOURCE_EXHAUSTED" not in str(gemini_error):
                        raise
                    if not OPENROUTER_API_KEY:
                        raise RuntimeError(
                            "حصة Gemini سالات (429)، وما كاينش OPENROUTER_API_KEY محفوظ كبديل. "
                            "زيد مفتاح OpenRouter فـ Streamlit Secrets أو تسنى حتى ترجع الحصة."
                        )
                    st.warning("Gemini وصل للحد المجاني؛ كنحوّل تلقائياً إلى OpenRouter مع عناوين Google News RSS.")
                    draft = research_with_openrouter_rss(auto_topic.strip(), OPENROUTER_API_KEY)
            if len(draft.strip()) < 40:
                raise ValueError("البحث ما رجعش سيناريو كافي. عاود المحاولة.")
            st.session_state["video_research_draft"] = draft
            st.session_state["video_topic"] = auto_topic.strip()
            with st.spinner("2/2 كنركّب الفيديو بالصوت والصور والحركة..."):
                video_bytes = build_vertical_video(
                    auto_topic.strip(), draft.strip()
                )
            st.session_state["generated_video"] = video_bytes
            st.session_state["generated_video_script"] = draft
            st.success("الفيديو تصاوب بنجاح. تقدر تشوفو وتحملو من هنا.")
        except Exception as e:
            safe_error = str(e).replace(GEMINI_API_KEY, "[API KEY HIDDEN]")
            st.error("ما كملش إنشاء الفيديو هاد المرة.")
            st.code(safe_error[:1600])

if st.session_state.get("generated_video"):
    st.video(st.session_state["generated_video"])
    st.download_button(
        "⬇️ حمّل الفيديو MP4",
        data=st.session_state["generated_video"],
        file_name="CHNO_WA9E3_video.mp4",
        mime="video/mp4",
        use_container_width=True
    )
    with st.expander("شوف السيناريو والمصادر"):
        st.text(st.session_state.get("generated_video_script", ""))

st.caption("هاد الزر كيدير البحث والسيناريو والمونتاج دفعة وحدة. خاص الموقع يبقى محلول أثناء الخدمة. النشر التلقائي وجدولة الفيديوهات مازال ما تفعّلوش.");
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
