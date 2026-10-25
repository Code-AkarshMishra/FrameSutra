from __future__ import annotations

import json
import os
import re
import time
import threading
import uuid
from html import escape
from pathlib import Path

from core.config import load_project_env
load_project_env()

import streamlit as st

from core.analyzer import analyze_transcript, fallback_analysis, is_rate_limit_error
from core.rag_engine import ask_question, build_rag_chain
from core.transcriber import transcribe_all
from utils.audio_processor import process_input
from core.visual_analyzer import analyze_local_video

APP_VERSION = "0.4.1"
_PIPELINE_LOCK = threading.Lock()
_PROGRESS_SLOT = None
PIPELINE_STEPS = [
    ("audio", "Prepare source", "Download or convert audio and split it into processable chunks."),
    ("transcript", "Transcribe speech", "Whisper handles English locally; Sarvam handles Hinglish transcription/translation."),
    ("title", "Understand the video", "Generate a clear title and structured summary."),
    ("summary", "Summarize key points", "Organize the main ideas into readable sections."),
    ("extract", "Extract insights", "Identify action items, decisions and open questions."),
    ("visual", "Analyze visuals", "Optional frame analysis for supported local video files."),
    ("rag", "Prepare AI chat", "Index transcript and available visual evidence for grounded Q&A."),
]

st.set_page_config(page_title="FrameSutra | Every Frame Has a Story", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

st.markdown(r'''
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root{--ink:#14213d;--muted:#65748b;--line:#e4eaf3;--blue:#365cf5;--blue2:#6b7dff;--cyan:#23b7cc;--paper:#f5f7fc;--panel:#fff;--green:#12a879;--rose:#ef6477;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:var(--paper);color:var(--ink)}
[data-testid="stHeader"]{background:rgba(245,247,252,.78)}
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none!important}
.block-container{max-width:1420px;padding-top:1rem;padding-bottom:4rem}
h1,h2,h3,h4{font-family:'Manrope',sans-serif!important;color:var(--ink)!important;letter-spacing:-.035em}
h1{font-weight:800!important;line-height:1.04!important}
p,li,label,.stCaption{color:#52617a}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px!important;border-color:var(--line)!important;background:rgba(255,255,255,.80)}
.stButton button,.stFormSubmitButton button{border-radius:12px;min-height:2.7rem;font-weight:700;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.stButton button:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(54,92,245,.14)}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]{background:#365cf5;border-color:var(--blue);color:white}
.stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"]{border-radius:12px!important;border-color:#dbe3ef!important;background:#fff}
[data-testid="stFileUploader"]{border:1.5px dashed #c8d4e9;border-radius:16px;background:#fafdff;padding:.55rem}
[data-testid="stTabs"] button{font-weight:700;padding-top:.8rem;padding-bottom:.8rem}
[data-testid="stTabs"] button[aria-selected="true"]{color:var(--blue)!important}
[data-testid="stAlert"]{border-radius:14px;overflow-wrap:anywhere}
[data-testid="stAlert"] p{overflow-wrap:anywhere;line-height:1.55}
[data-testid="stStatusWidget"]{border-radius:16px;border:1px solid #dae3f1;background:#fff}
.stSpinner>div{border-top-color:var(--blue)!important}

/* App navigation */
.navbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.7rem 0 1.2rem;margin-bottom:.25rem;border-bottom:1px solid rgba(209,219,235,.78)}
.brand{display:flex;align-items:center;gap:.7rem;font-family:'Manrope',sans-serif;font-weight:800;font-size:1.03rem;letter-spacing:-.04em;color:#172440}
.brand-mark{width:2.55rem;height:2.55rem;display:grid;place-items:center;color:#fff;border-radius:13px;background:#365cf5;box-shadow:0 8px 19px rgba(54,92,245,.23);font-size:1.2rem}
.nav-links{display:flex;align-items:center;gap:1.4rem;color:#65748b;font-weight:650;font-size:.88rem}
.nav-links a{color:#65748b;text-decoration:none}.nav-links a:hover{color:var(--blue)}
.local-pill{border:1px solid #dce7f6;background:#fff;border-radius:999px;padding:.42rem .75rem;color:#47627f;font-size:.75rem;font-weight:700;white-space:nowrap}

/* Landing screen */
.splash-screen{position:fixed;inset:0;z-index:99999;background:#111827;display:flex;align-items:center;justify-content:center;color:#fff;animation:splashOut .75s ease 1.05s forwards;pointer-events:none}
.splash-inner{text-align:center;animation:splashIn .5s ease both}.splash-logo{width:4.4rem;height:4.4rem;margin:0 auto 1rem;display:grid;place-items:center;border:1px solid rgba(255,255,255,.35);border-radius:22px;background:rgba(255,255,255,.14);font-size:2rem;box-shadow:0 15px 40px rgba(0,0,0,.16)}
.splash-title{font:800 1.45rem 'Manrope',sans-serif;letter-spacing:-.04em;color:#fff}.splash-sub{font-size:.84rem;color:#dce8ff;margin-top:.45rem}.splash-track{height:4px;width:190px;border-radius:20px;background:rgba(255,255,255,.24);margin:1.25rem auto 0;overflow:hidden}.splash-track span{display:block;height:100%;background:#fff;width:100%;border-radius:20px}
@keyframes splashOut{to{opacity:0;visibility:hidden}}@keyframes splashIn{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:none}}
.hero-shell{position:relative;overflow:hidden;border:1px solid #dce6f6;border-radius:28px;background:#ffffff;padding:clamp(1.4rem,4vw,3.5rem);box-shadow:0 18px 48px rgba(24,49,98,.06)}
.hero-shell:after{content:'';position:absolute;right:-6rem;top:-8rem;width:20rem;height:20rem;border-radius:50%;border:1px solid rgba(54,92,245,.10);box-shadow:0 0 0 18px rgba(54,92,245,.025),0 0 0 36px rgba(54,92,245,.02);pointer-events:none}
.eyebrow{font-size:.72rem;letter-spacing:.18em;text-transform:uppercase;color:var(--blue);font-weight:800;display:flex;align-items:center;gap:.55rem;margin-bottom:1rem}
.eyebrow:before{content:'';height:2px;width:25px;background:var(--blue);border-radius:3px}
.hero-title{font-family:'Manrope',sans-serif;font-size:clamp(2.5rem,5.7vw,5rem);font-weight:800;letter-spacing:-.065em;line-height:.99;color:#14213d;margin:0;max-width:880px}
.hero-gradient{color:#365cf5}
.hero-copy{max-width:730px;font-size:1.03rem;line-height:1.8;color:#617089;margin-top:1.15rem}
.hero-tags{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1.25rem}.hero-tag{background:rgba(255,255,255,.84);border:1px solid #dbe5f4;color:#4d607d;padding:.48rem .7rem;border-radius:999px;font-weight:650;font-size:.77rem}
.section-heading{font-family:'Manrope',sans-serif;font-size:1.5rem;font-weight:800;letter-spacing:-.045em;color:#172440;margin:.5rem 0 .2rem}.section-subtitle{font-size:.9rem;color:#718097;margin:0 0 1.1rem}
.feature-card{background:#fff;border:1px solid #e1e8f2;border-radius:18px;padding:1.2rem;height:100%;min-height:155px;box-shadow:0 7px 23px rgba(25,45,85,.035);transition:transform .2s ease,border-color .2s ease}
.feature-card:hover{transform:translateY(-3px);border-color:#b6c9fa}.feature-icon{width:2.6rem;height:2.6rem;display:grid;place-items:center;border-radius:13px;background:#eef3ff;color:#315cf5;font-size:1.15rem;margin-bottom:1rem}.feature-title{font-weight:800;color:#1a2a48;margin-bottom:.45rem}.feature-desc{font-size:.85rem;color:#6d7b91;line-height:1.65}
.how-card{display:flex;gap:.9rem;background:#fff;border:1px solid #e2e9f3;border-radius:16px;padding:1rem;height:100%}.how-no{flex:0 0 2.35rem;width:2.35rem;height:2.35rem;border-radius:11px;display:grid;place-items:center;background:#eef3ff;color:var(--blue);font-weight:800}.how-title{font-weight:800;color:#1b2945;margin-bottom:.25rem}.how-copy{font-size:.83rem;line-height:1.6;color:#6c7a91}
.step-bar{display:flex;align-items:center;gap:.55rem;margin:0 0 1.2rem;flex-wrap:wrap}.step-pill{display:flex;align-items:center;gap:.45rem;padding:.55rem .8rem;border-radius:999px;border:1px solid #dce5f2;background:white;color:#718099;font-size:.79rem;font-weight:750}.step-pill.active{background:#edf2ff;border-color:#aabdfb;color:#315cf5;box-shadow:0 0 0 3px rgba(54,92,245,.06)}.step-pill.done{background:#eafaf4;border-color:#bcebd9;color:#0c9468}.step-number{display:grid;place-items:center;width:1.35rem;height:1.35rem;border-radius:50%;background:#eef1f7;color:#63728b;font-size:.72rem}.step-pill.active .step-number{background:#315cf5;color:white}.step-pill.done .step-number{background:#10a879;color:white}
.choice-label{font-size:.72rem;letter-spacing:.13em;text-transform:uppercase;font-weight:800;color:#8492a9;margin-bottom:.4rem}.source-card-title{font-family:'Manrope',sans-serif;font-size:1.15rem;font-weight:800;letter-spacing:-.03em;color:#1a2948}.source-card-copy{font-size:.84rem;line-height:1.6;color:#718097;margin:.35rem 0 .7rem}
.progress-rail{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem;margin:.4rem 0 1.2rem}.progress-stage{position:relative;background:#fff;border:1px solid #e2e9f3;border-radius:14px;padding:.85rem;overflow:hidden}.progress-stage:before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:#dbe3f0}.progress-stage.active{border-color:#9eb5ff;box-shadow:0 0 0 3px rgba(54,92,245,.06)}.progress-stage.active:before{background:var(--blue);animation:stageGlow 1.2s ease-in-out infinite alternate}.progress-stage.done:before{background:var(--green)}.progress-stage.error:before{background:var(--rose)}.stage-title{font-weight:800;font-size:.84rem;color:#253653}.stage-sub{font-size:.73rem;color:#8390a6;margin-top:.25rem;line-height:1.4}@keyframes stageGlow{from{opacity:.45}to{opacity:1}}
.metric-card{height:100%;border:1px solid #e0e8f4;background:#fff;border-radius:18px;padding:1rem 1.15rem;box-shadow:0 7px 24px rgba(28,48,87,.035)}.metric-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:#8592a7}.metric-value{font:800 1.65rem 'Manrope',sans-serif;color:#1b2a49;margin-top:.3rem;overflow-wrap:anywhere}.metric-caption{font-size:.75rem;color:#8794a8;margin-top:.25rem}
.summary-panel{border:1px solid #dce6f4;border-radius:18px;background:#fff;padding:1.35rem;line-height:1.8}.insight-card{border:1px solid #e1e8f1;border-radius:17px;background:#fff;padding:1.15rem;height:100%}.insight-card h4{font-size:1rem!important;letter-spacing:-.02em;margin:0 0 .8rem}.transcript-box{border:1px solid #e0e8f3;background:#fff;border-radius:16px;padding:1.25rem;max-height:550px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:#34445f;line-height:1.85;font-size:.92rem}
.chat-shell{border:1px solid #dae4f4;border-radius:22px;background:#fff;padding:1rem;position:relative;overflow:hidden}.chat-glow{height:4px;border-radius:99px;background:#365cf5;margin:-1rem -1rem 1rem}.download-card{border:1px solid #e0e8f3;background:#fff;border-radius:16px;padding:1.1rem;height:100%}
.footer{border-top:1px solid #e1e8f2;margin-top:3rem;padding-top:1.3rem;color:#8794a8;font-size:.78rem}
@media(max-width:1000px){.nav-links{display:none}.progress-rail{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.block-container{padding-left:1rem;padding-right:1rem}.hero-shell{border-radius:20px;padding:1.25rem}.progress-rail{grid-template-columns:1fr 1fr}.feature-card{min-height:0}}
</style>
''', unsafe_allow_html=True)


def init_state() -> None:
    defaults = {
        "page": "home", "splash_seen": False, "selected_language": "English", "theme_mode": "Light",
        "result": None, "prepared_source": None, "prepared_language": None,
        "prepared_chunks": None, "prepared_transcript": None, "prepared_analysis": None,
        "chat_history": [], "pipeline_steps": {}, "last_error": None,
        "last_failed_step": None, "retry_source": None, "retry_language": None,
        "include_visuals": False, "visual_evidence": [],
        "visual_interval_seconds": 60, "max_visual_frames": 80,
        "youtube_url": "", "uploaded_source": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def env_present(name: str) -> bool:
    value = os.getenv(name, "").strip()
    if not value:
        return False
    lowered = value.lower()
    placeholders = ("your_actual_", "your_real_", "replace_with_", "your_groq_api_key_here", "your_sarvam_api_key_here")
    return not any(marker in lowered for marker in placeholders)


def check_environment(language: str) -> list[str]:
    missing = []
    if not env_present("GROQ_API_KEY"):
        missing.append("GROQ_API_KEY")
    if language.lower() == "hinglish" and not env_present("SARVAM_API_KEY"):
        missing.append("SARVAM_API_KEY")
    return missing


def update_step(key: str, state: str) -> None:
    st.session_state.pipeline_steps[key] = state
    # Update the visible progress cards immediately while the synchronous pipeline runs.
    slot = globals().get("_PROGRESS_SLOT")
    if slot is not None:
        render_step_status(slot)


def render_theme_styles() -> None:
    """Apply a consistent high-contrast palette to all Streamlit pages."""
    if st.session_state.get("theme_mode", "Light") != "Dark":
        return
    st.markdown(r'''<style>
    :root{--ink:#edf2ff;--muted:#aab6cc;--line:#303b50;--paper:#111827;--panel:#182235;--blue:#7c9cff;--green:#35d49a;--rose:#ff7d91}
    .stApp{background:#111827!important;color:#edf2ff!important}
    [data-testid="stHeader"]{background:#111827!important}
    h1,h2,h3,h4,.brand,.hero-title,.section-heading,.feature-title,.how-title,.source-card-title,.stage-title{color:#edf2ff!important}
    p,li,label,.stCaption,.hero-copy,.section-subtitle,.feature-desc,.how-copy,.source-card-copy,.stage-sub{color:#b4c0d5!important}
    [data-testid="stVerticalBlockBorderWrapper"],.hero-shell,.feature-card,.how-card,.progress-stage,.metric-card,.summary-panel,.insight-card,.transcript-box,.chat-shell,.download-card{background:#182235!important;border-color:#34425b!important;color:#edf2ff!important}
    .hero-shell:after{border-color:#405a91!important}
    .hero-tags .hero-tag,.step-pill,.local-pill{background:#202d43!important;border-color:#3b4c68!important;color:#d5def0!important}
    .feature-icon,.how-no,.step-number{background:#26395c!important;color:#a9bdff!important}
    .step-pill.active{background:#26395c!important;border-color:#7c9cff!important;color:#c8d5ff!important}
    .step-pill.done{background:#173d35!important;border-color:#246b58!important;color:#8df0ca!important}
    .stTextInput input,.stTextArea textarea,.stSelectbox div[data-baseweb="select"], [data-testid="stFileUploader"]{background:#111b2b!important;color:#edf2ff!important;border-color:#465675!important}
    [data-testid="stStatusWidget"]{background:#182235!important;border-color:#34425b!important}
    [data-testid="stAlert"]{background:#202d43!important;color:#edf2ff!important}
    .footer{color:#aab6cc!important;border-color:#34425b!important}
    .brand-mark{background:#365cf5!important}
    </style>''', unsafe_allow_html=True)


def render_navbar(current_page: str) -> None:
    left, middle, right = st.columns([2.4, 3.2, 1.25], vertical_alignment="center")
    with left:
        st.markdown('<div class="brand"><span class="brand-mark">FS</span><span>Frame<span style="color:#365cf5">Sutra</span><div style="font:500 .68rem \'DM Sans\',sans-serif;color:#8190a6;letter-spacing:.02em;margin-top:.08rem">AI VIDEO UNDERSTANDING</div></span></div>', unsafe_allow_html=True)
    with middle:
        st.markdown('<div class="nav-links"><a href="#features">Features</a><a href="#how-to-use">How to use</a><a href="#privacy">Local-first workflow</a></div>', unsafe_allow_html=True)
    with right:
        st.selectbox("Theme", ["Light", "Dark"], key="theme_mode", label_visibility="collapsed", help="Switch between light and dark themes")
        if st.button("Start analysis →" if current_page == "home" else "Home", type="primary" if current_page == "home" else "secondary", use_container_width=True, key=f"navbar_action_{current_page}"):
            if current_page == "home":
                st.session_state.page = "setup"
            else:
                st.session_state.page = "home"
            st.rerun()
    st.markdown('<div style="display:flex;justify-content:flex-end;margin-top:-.2rem;margin-bottom:.5rem"><span class="local-pill">● Built for local run &nbsp;·&nbsp; v0.4.1</span></div>', unsafe_allow_html=True)


def render_splash_once() -> None:
    if not st.session_state.splash_seen:
        st.markdown('''<div class="splash-screen"><div class="splash-inner"><div class="splash-logo">▶</div><div class="splash-title">FrameSutra AI</div><div class="splash-sub">Your video workspace is ready</div><div class="splash-track"><span></span></div></div></div>''', unsafe_allow_html=True)
        st.session_state.splash_seen = True


def render_step_status(slot=None) -> None:
    state_to_class = {"active": "active", "done": "done", "error": "error", "skipped": ""}
    chunks = []
    for index, (key, label, description) in enumerate(PIPELINE_STEPS, start=1):
        state = st.session_state.pipeline_steps.get(key, "pending")
        cls = state_to_class.get(state, "")
        mark = "✓" if state == "done" else ("!" if state == "error" else str(index))
        detail = "Skipped for this source" if state == "skipped" else description
        chunks.append(f'<div class="progress-stage {cls}"><div class="stage-title"><span style="color:#365cf5;margin-right:.35rem">{mark}</span>{escape(label)}</div><div class="stage-sub">{escape(detail)}</div></div>')
    completed = sum(1 for key, _, _ in PIPELINE_STEPS if st.session_state.pipeline_steps.get(key) in ("done", "skipped"))
    total = len(PIPELINE_STEPS)
    active = next((label for key, label, _ in PIPELINE_STEPS if st.session_state.pipeline_steps.get(key) == "active"), None)
    state_line = f"{completed}/{total} pipeline stages complete"
    if active:
        state_line += f" · Currently: {escape(active)}"
    html = (f'<div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin:.4rem 0 .7rem;color:var(--muted);font-size:.84rem;font-weight:700">'
            f'<span>◷ {state_line}</span><span>Stage-based progress · no fabricated ETA</span></div>'
            '<div class="progress-rail">' + ''.join(chunks) + '</div>')
    if slot is not None:
        slot.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_home() -> None:
    st.markdown('''
    <section class="hero-shell">
      <div class="eyebrow">Local-first AI · Video intelligence · RAG-powered</div>
      <h1 class="hero-title">Every frame has a story.<br><span class="hero-gradient">Every word has an answer.</span></h1>
      <p class="hero-copy">Analyze YouTube videos or upload local audio and video. Get a structured summary, searchable transcript, key decisions, action items, visual notes and an AI chat grounded in your content.</p>
      <div class="hero-tags"><span class="hero-tag">◈ English · Local Whisper</span><span class="hero-tag">◈ Hinglish · Sarvam AI</span><span class="hero-tag">◈ Transcript-grounded chat</span><span class="hero-tag">◈ Export your findings</span></div>
    </section>
    ''', unsafe_allow_html=True)
    st.write("")
    a, b = st.columns([1.05, 2.1], gap="large", vertical_alignment="center")
    with a:
        if st.button("Start Analysis  →", type="primary", use_container_width=True, key="hero_start"):
            st.session_state.page = "setup"
            st.rerun()
        st.caption("No cloud upload of local source files is required for English transcription. AI summaries and chat use your configured Groq API.")
    with b:
        st.markdown('<div style="display:flex;gap:1rem;flex-wrap:wrap;justify-content:space-around;padding:1rem;border:1px solid #e0e8f4;background:rgba(255,255,255,.72);border-radius:18px"><div><div style="font:800 1.35rem Manrope;color:#203250">01</div><div style="font-size:.78rem;color:#718097">Choose language</div></div><div style="font-size:1.1rem;color:#b4c1d6;align-self:center">→</div><div><div style="font:800 1.35rem Manrope;color:#203250">02</div><div style="font-size:.78rem;color:#718097">Add your video</div></div><div style="font-size:1.1rem;color:#b4c1d6;align-self:center">→</div><div><div style="font:800 1.35rem Manrope;color:#203250">03</div><div style="font-size:.78rem;color:#718097">Review results</div></div></div>', unsafe_allow_html=True)

    st.markdown('<div id="features" class="section-heading" style="margin-top:2.4rem">One workspace. The whole story.</div><p class="section-subtitle">Move from raw media to useful notes without switching between tools.</p>', unsafe_allow_html=True)
    feature_cols = st.columns(4, gap="medium")
    features = [
        ("◉", "Smart transcription", "English uses local Whisper. Hinglish uses Sarvam speech-to-text translation."),
        ("✧", "Structured insights", "Get the summary, key decisions, next actions and questions in separate sections."),
        ("⌕", "Ask your video", "Chat with an indexed transcript and receive answers grounded in its content."),
        ("⇩", "Export and revisit", "Download transcript, summary and a portable JSON report for later reference."),
    ]
    for col, item in zip(feature_cols, features):
        icon, title, desc = item
        with col:
            st.markdown(f'<div class="feature-card"><div class="feature-icon">{icon}</div><div class="feature-title">{title}</div><div class="feature-desc">{desc}</div></div>', unsafe_allow_html=True)

    st.markdown('<div id="how-to-use" class="section-heading" style="margin-top:2.4rem">How to use</div><p class="section-subtitle">Four simple steps from video to answers.</p>', unsafe_allow_html=True)
    how = [
        ("01", "Choose the speech language", "Pick English for mostly English speech, or Hinglish for mixed Hindi-English speech."),
        ("02", "Select either input method", "Paste a public YouTube URL or upload a local video/audio file. Both options stay visible."),
        ("03", "Watch analysis progress", "Follow source preparation, transcription, summarization, insight extraction and indexing."),
        ("04", "Explore and download", "Read the summary, play audio chunks, browse visuals, chat with the transcript and export results."),
    ]
    cols = st.columns(2, gap="medium")
    for i, (number, title, desc) in enumerate(how):
        with cols[i % 2]:
            st.markdown(f'<div class="how-card"><div class="how-no">{number}</div><div><div class="how-title">{title}</div><div class="how-copy">{desc}</div></div></div>', unsafe_allow_html=True)
        if i in (1,):
            st.write("")
    st.markdown('<div id="privacy" class="footer">FrameSutra · Built with effort by Akarsh Mishra. Local files are processed on this machine. Hinglish audio and enabled AI analysis/visual features may send content to configured providers. Visual analysis is optional and supports local video files.</div>', unsafe_allow_html=True)


def render_setup_page() -> None:
    st.markdown('<div class="eyebrow">Setup · Step by step</div><h1 style="font-size:2.45rem">Let’s set up your analysis.</h1><p class="section-subtitle">Choose the language first, then select your source. YouTube link and file upload are separate options.</p>', unsafe_allow_html=True)
    st.markdown('<div class="step-bar"><span class="step-pill done"><span class="step-number">✓</span>Welcome</span><span class="step-pill active"><span class="step-number">1</span>Language & source</span><span class="step-pill"><span class="step-number">2</span>Processing</span><span class="step-pill"><span class="step-number">3</span>Results</span></div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="choice-label">01 · Speech language</div><div class="source-card-title">What language is spoken in the video?</div><div class="source-card-copy">This selects the transcription engine. The generated transcript is in English for both modes.</div>', unsafe_allow_html=True)
        lang_choice = st.segmented_control("Language mode", options=["English", "Hinglish"], default=st.session_state.selected_language, key="language_mode_control", label_visibility="collapsed")
        st.session_state.selected_language = lang_choice or "English"
        l1, l2 = st.columns(2, gap="medium")
        with l1:
            st.markdown('<div class="how-card"><div class="how-no">EN</div><div><div class="how-title">Pure English / English speech</div><div class="how-copy">Transcription uses OpenAI Whisper running locally on this machine. Sarvam is not required.</div></div></div>', unsafe_allow_html=True)
        with l2:
            st.markdown('<div class="how-card"><div class="how-no">हि</div><div><div class="how-title">Hinglish / Hindi + English</div><div class="how-copy">Uses Sarvam’s speech-to-text-translate API. A valid Sarvam API key is required.</div></div></div>', unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="choice-label">02 · Video source</div><div class="section-heading">Where is your video?</div><p class="section-subtitle">Use either option. Choosing one does not remove the other.</p>', unsafe_allow_html=True)
    youtube_col, upload_col = st.columns(2, gap="large")
    with youtube_col:
        with st.container(border=True):
            st.markdown('<div class="feature-icon">↗</div><div class="source-card-title">Paste a YouTube link</div><div class="source-card-copy">Best for public YouTube videos. The app downloads audio only for transcription.</div>', unsafe_allow_html=True)
            st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=…", key="youtube_url", help="Paste the full link or the youtu.be short link.")
            preview_url = (st.session_state.get("youtube_url") or "").strip()
            if preview_url.startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/")):
                with st.expander("▶ Preview selected YouTube video", expanded=True):
                    st.video(preview_url)
                    st.caption(f"Selected source: {preview_url}")
            if st.button("Analyze YouTube link →", type="primary", use_container_width=True, key="analyze_youtube"):
                source = (st.session_state.get("youtube_url") or "").strip()
                if not source:
                    st.error("Paste a YouTube video URL first.")
                elif not source.startswith(("https://", "http://")):
                    st.error("Please enter a valid YouTube URL beginning with http:// or https://.")
                else:
                    _start_analysis(source, st.session_state.selected_language.lower(), include_visuals=False)
    with upload_col:
        with st.container(border=True):
            st.markdown('<div class="feature-icon">⇧</div><div class="source-card-title">Upload a video or audio file</div><div class="source-card-copy">For local files. Visual frame analysis can be enabled for supported video formats.</div>', unsafe_allow_html=True)
            uploaded = st.file_uploader("Select a local file", type=["mp4", "mov", "mkv", "webm", "avi", "m4v", "mp3", "wav", "m4a", "mpeg", "mpga", "ogg", "flac"], key="source_upload", help="Maximum upload size follows your Streamlit server configuration.")
            video_exts = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
            is_video = bool(uploaded and Path(uploaded.name).suffix.lower() in video_exts)
            include_visuals = st.checkbox("Enable visual frame analysis (local video only)", value=False, key="upload_include_visuals", disabled=not is_video, help="Selected frames and their descriptions are sent to your configured Groq Vision endpoint when enabled.")
            visual_options = st.expander("Visual sampling options", expanded=False)
            with visual_options:
                visual_interval = st.slider("Minimum frame sampling interval", 15, 300, 60, 15, key="upload_visual_interval", disabled=not include_visuals)
                max_frames = st.slider("Maximum frames to describe", 10, 120, 40, 10, key="upload_max_frames", disabled=not include_visuals)
            if st.button("Analyze uploaded file →", type="primary", use_container_width=True, key="analyze_uploaded", disabled=uploaded is None):
                if uploaded is None:
                    st.error("Select a file first.")
                else:
                    upload_dir = Path(__file__).resolve().parent / "downloads" / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    ext = Path(uploaded.name).suffix.lower()
                    safe_name = f"upload_{uuid.uuid4().hex[:10]}{ext}"
                    saved_path = upload_dir / safe_name
                    saved_path.write_bytes(uploaded.getbuffer())
                    _start_analysis(str(saved_path), st.session_state.selected_language.lower(), bool(include_visuals), visual_interval, max_frames)

    st.write("")
    back_col, note_col = st.columns([1, 3], vertical_alignment="center")
    with back_col:
        if st.button("← Back to home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    with note_col:
        st.caption("Setup status: Groq is required for AI summary and chat. Sarvam is required only for Hinglish. Local English transcription uses Whisper and FFmpeg.")


def _start_analysis(source: str, language: str, include_visuals: bool = False, interval: int = 60, max_frames: int = 40) -> None:
    missing = check_environment(language)
    if missing:
        st.error("Missing required setting(s): " + ", ".join(missing) + ". Add the values to your project .env and restart the app; do not paste keys in chat.")
        return
    st.session_state.page = "analysis"
    st.session_state.last_error = None
    st.session_state.retry_source = source
    st.session_state.retry_language = language
    st.session_state.pending_run = {"source": source, "language": language, "include_visuals": include_visuals, "interval": interval, "max_frames": max_frames}
    st.rerun()


def _launch_pending_run() -> None:
    pending = st.session_state.pop("pending_run", None)
    if pending:
        run_pipeline(pending["source"], pending["language"], pending["include_visuals"], pending["interval"], pending["max_frames"])


def render_analysis_page() -> None:
    global _PROGRESS_SLOT
    st.markdown('<div class="eyebrow">Processing workspace · Live status</div><h1 style="font-size:2.35rem">Analyzing your video</h1><p class="section-subtitle">Progress reflects completed pipeline stages and real transcription chunk callbacks. Embedding/model downloads can take longer on the first run.</p>', unsafe_allow_html=True)
    _PROGRESS_SLOT = st.empty()
    render_step_status(_PROGRESS_SLOT)
    render_retry_panel()
    if not st.session_state.last_error and not st.session_state.result:
        st.info("Pipeline runs synchronously in this Streamlit process. Keep this tab open; first-time model downloads and RAG indexing may take several minutes.", icon="⏳")
    c1, c2 = st.columns([1, 4], vertical_alignment="center")
    with c1:
        if st.button("← Change source", use_container_width=True):
            st.session_state.page = "setup"
            st.rerun()
    with c2:
        source = st.session_state.get("retry_source") or ""
        st.caption(f"Source: {Path(source).name if not source.startswith(('http://','https://')) else source[:90]}")


def render_retry_panel() -> None:
    if not st.session_state.last_error:
        return
    failed_step = st.session_state.last_failed_step or "pipeline"
    with st.container(border=True):
        st.error(st.session_state.last_error, icon=":material/error:")
        st.caption("Retry reuses the latest completed transcript/analysis checkpoint when possible.")
        if st.button(f"Retry {failed_step} step", icon=":material/replay:", type="primary", key="retry_failed_step"):
            run_pipeline(st.session_state.retry_source, st.session_state.retry_language, st.session_state.get("include_visuals", False), st.session_state.get("visual_interval_seconds", 60), st.session_state.get("max_visual_frames", 40))


def _item_count(text: str) -> int:
    if not text or text.strip().lower().startswith("no "):
        return 0
    return sum(1 for line in text.splitlines() if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line))


def render_results() -> None:
    result = st.session_state.result
    if not result:
        st.info("No finished analysis yet. Start a video analysis to see results here.")
        if st.button("Start a new analysis", type="primary"):
            st.session_state.page = "setup"
            st.rerun()
        return

    st.markdown('<div class="eyebrow">Your results are ready</div>', unsafe_allow_html=True)
    st.title(result.get("title") or "Video analysis")
    if result.get("used_fallback"):
        st.warning("This result used a transcript-based fallback because Groq was rate-limited. The transcript is preserved; retry when the API is available for richer analysis.")
    transcript = result.get("transcript", "") or ""
    word_count = len(re.findall(r"\b[\w’'-]+\b", transcript))
    duration_chunks = len(result.get("audio_chunks") or [])
    metrics = st.columns(4, gap="medium")
    metric_items = [("LANGUAGE MODE", result.get("language", "english").title(), "Selected speech routing"), ("AUDIO CHUNKS", str(result.get("chunk_count", duration_chunks)), "Processed segments"), ("TRANSCRIPT WORDS", f"{word_count:,}", "Recognized words"), ("VISUAL FRAMES", str(len(result.get("visual_evidence") or [])), "Descriptions indexed")]
    for col, item in zip(metrics, metric_items):
        label, value, caption = item
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-label">{escape(label)}</div><div class="metric-value">{escape(value)}</div><div class="metric-caption">{escape(caption)}</div></div>', unsafe_allow_html=True)

    summary_tab, insights_tab, transcript_tab, visual_tab, chat_tab, downloads_tab = st.tabs(["✧ Summary", "✓ Actions & decisions", "◉ Transcript + audio", "▧ Visuals", "✦ AI chat", "⇩ Downloads"])
    with summary_tab:
        col_summary, col_quick = st.columns([1.8, 1], gap="large")
        with col_summary:
            st.markdown('<div class="section-heading">Executive summary</div><p class="section-subtitle">The key message, organized for quick reading.</p>', unsafe_allow_html=True)
            st.markdown('<div class="summary-panel">' + escape(result.get("summary", "No summary available.")).replace("\n", "<br>") + '</div>', unsafe_allow_html=True)
        with col_quick:
            st.markdown('<div class="section-heading">At a glance</div><p class="section-subtitle">Signals extracted from this transcript.</p>', unsafe_allow_html=True)
            st.markdown('<div class="insight-card"><div class="metric-label">ACTION ITEMS</div><div class="metric-value">' + str(_item_count(result.get("action_items", ""))) + '</div><div class="metric-caption">Tasks or follow-ups detected</div><hr style="border:0;border-top:1px solid #e6ebf4;margin:1rem 0"><div class="metric-label">KEY DECISIONS</div><div class="metric-value">' + str(_item_count(result.get("key_decisions", ""))) + '</div><div class="metric-caption">Decisions extracted</div><hr style="border:0;border-top:1px solid #e6ebf4;margin:1rem 0"><div class="metric-label">OPEN QUESTIONS</div><div class="metric-value">' + str(_item_count(result.get("open_questions", ""))) + '</div><div class="metric-caption">Questions requiring follow-up</div></div>', unsafe_allow_html=True)

        timestamp_pattern = re.compile(r"\[Approx\. timestamp\s+(\d{2}:\d{2}:\d{2})\]\s*")
        matches = list(timestamp_pattern.finditer(transcript))
        rows = []
        for i, match in enumerate(matches):
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(transcript)
            body = transcript[match.end():body_end].replace("\\n", " ").replace("\\r", " ")
            rows.append({"Segment": match.group(1), "Words": len(re.findall(r"\b[\w’'-]+\b", body))})
        st.markdown('<div class="section-heading" style="margin-top:1.7rem">Transcript volume</div><p class="section-subtitle">Word counts per approximate audio chunk. These are segment start times, not word-level timestamps.</p>', unsafe_allow_html=True)
        if rows:
            spec = {"$schema":"https://vega.github.io/schema/vega-lite/v5.json","data":{"values":rows},"width":"container","height":220,"mark":{"type":"bar","color":"#365cf5","cornerRadiusTopLeft":5,"cornerRadiusTopRight":5},"encoding":{"x":{"field":"Segment","type":"ordinal","sort":None,"axis":{"title":"Approximate segment start","labelAngle":-25}},"y":{"field":"Words","type":"quantitative","scale":{"zero":True,"domainMin":0},"axis":{"title":"Word count","format":"d","tickMinStep":1}},"tooltip":[{"field":"Segment","type":"ordinal"},{"field":"Words","type":"quantitative","format":"d"}]},"config":{"view":{"stroke":None},"axis":{"gridColor":"#e5eaf3","labelColor":"#687791","titleColor":"#687791"}}}
            st.vega_lite_chart(spec=spec, use_container_width=True)
        else:
            st.info("No timestamped segments were stored in this transcript, so the word-volume chart is unavailable.")

    with insights_tab:
        categories = [("Action items", result.get("action_items", ""), "#365cf5"), ("Key decisions", result.get("key_decisions", ""), "#22a7c1"), ("Open questions", result.get("open_questions", ""), "#ed7182")]
        st.markdown('<div class="section-heading">Insights at a glance</div><p class="section-subtitle">Review each output separately, without mixing tasks and decisions together.</p>', unsafe_allow_html=True)
        chart_rows = [{"Category": title, "Count": _item_count(value)} for title, value, _ in categories]
        spec = {"$schema":"https://vega.github.io/schema/vega-lite/v5.json","data":{"values":chart_rows},"width":"container","height":170,"mark":{"type":"bar","cornerRadiusEnd":6},"encoding":{"y":{"field":"Category","type":"ordinal","sort":["Action items","Key decisions","Open questions"],"axis":{"title":None}},"x":{"field":"Count","type":"quantitative","scale":{"zero":True,"domainMin":0},"axis":{"title":"Number of items","format":"d","tickMinStep":1}},"color":{"field":"Category","type":"nominal","legend":None,"scale":{"domain":[x[0] for x in categories],"range":[x[2] for x in categories]}},"tooltip":[{"field":"Category"},{"field":"Count","format":"d"}]},"config":{"view":{"stroke":None},"axis":{"gridColor":"#e5eaf3","labelColor":"#687791","titleColor":"#687791"}}}
        st.vega_lite_chart(spec=spec, use_container_width=True)
        cols = st.columns(3, gap="medium")
        for col, (title, value, color) in zip(cols, categories):
            with col:
                st.markdown(f'<div class="insight-card"><h4><span style="color:{color}">●</span> {escape(title)}</h4></div>', unsafe_allow_html=True)
                st.markdown(value or "No items identified.")

    with transcript_tab:
        st.markdown('<div class="section-heading">Transcript and audio playback</div><p class="section-subtitle">Play processed audio chunks while reading the transcript. Chunk timestamps are approximate.</p>', unsafe_allow_html=True)
        audio_chunks = result.get("audio_chunks") or []
        playable = [Path(p) for p in audio_chunks if p and Path(p).is_file()]
        if playable:
            if len(playable) == 1:
                path = playable[0]
                st.audio(path.read_bytes(), format="audio/wav")
            else:
                st.info(f"This source was split into {len(playable)} audio chunks. Open a chunk below to listen to it.")
                for i, path in enumerate(playable, start=1):
                    with st.expander(f"Audio segment {i} · {path.name}", expanded=(i == 1)):
                        st.audio(path.read_bytes(), format="audio/wav")
        else:
            st.info("Audio chunk files are not available at their saved paths. Transcript text and downloads are still available.")
        st.download_button("Download transcript (.txt)", transcript, file_name="video_transcript.txt", mime="text/plain", type="primary")
        st.markdown('<div class="transcript-box">' + escape(transcript) + '</div>', unsafe_allow_html=True)

    with visual_tab:
        visual_items = result.get("visual_evidence") or []
        st.markdown('<div class="section-heading">Visual timeline</div><p class="section-subtitle">Frame descriptions captured from local video input when visual analysis is enabled.</p>', unsafe_allow_html=True)
        if visual_items:
            for item in visual_items:
                with st.container(border=True):
                    left, right = st.columns([1, 2.3], gap="large")
                    with left:
                        frame_path = item.get("frame")
                        if frame_path and Path(frame_path).is_file():
                            st.image(frame_path, caption=item.get("timestamp", "Frame"), use_container_width=True)
                        else:
                            st.markdown(f'<div class="feature-icon">▧</div><strong>{escape(item.get("timestamp", "Frame"))}</strong>', unsafe_allow_html=True)
                    with right:
                        st.markdown(f'**{escape(item.get("timestamp", "Visual frame"))}**')
                        st.write(item.get("description", "No description available."))
        else:
            st.info("No visual evidence indexed. To analyze visuals, start with a local video file and enable visual frame analysis.")

    with chat_tab:
        st.markdown('<div class="chat-shell"><div class="chat-glow"></div><div class="section-heading">Ask your video</div><p class="section-subtitle">Ask for definitions, examples, a speaker’s explanation or where a topic appears. Answers are grounded in the indexed transcript and visual notes if present.</p></div>', unsafe_allow_html=True)
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        question = st.chat_input("Ask a question about this video…")
        if question:
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Searching relevant transcript sections…"):
                    answer = ask_question(result["rag_chain"], question)
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

    with downloads_tab:
        st.markdown('<div class="section-heading">Take your notes with you</div><p class="section-subtitle">Download the outputs from this analysis.</p>', unsafe_allow_html=True)
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", result.get("title", "video_analysis")).strip("_")[:70] or "video_analysis"
        summary_md = f"# {result.get('title', 'Video analysis')}\n\n## Summary\n\n{result.get('summary', '')}\n\n## Action items\n\n{result.get('action_items', '')}\n\n## Key decisions\n\n{result.get('key_decisions', '')}\n\n## Open questions\n\n{result.get('open_questions', '')}\n"
        report = {"title":result.get("title"),"source":result.get("source"),"language":result.get("language"),"chunk_count":result.get("chunk_count"),"summary":result.get("summary"),"action_items":result.get("action_items"),"key_decisions":result.get("key_decisions"),"open_questions":result.get("open_questions"),"transcript":transcript,"visual_evidence":[{"timestamp":i.get("timestamp"),"description":i.get("description")} for i in result.get("visual_evidence", [])]}
        c1, c2, c3 = st.columns(3, gap="medium")
        with c1:
            st.markdown('<div class="download-card"><div class="feature-icon">▤</div><div class="feature-title">Full transcript</div><div class="feature-desc">Recognized speech as plain text.</div></div>', unsafe_allow_html=True)
            st.download_button("Download TXT", transcript, f"{safe_title}_transcript.txt", "text/plain", use_container_width=True, key="dl_transcript")
        with c2:
            st.markdown('<div class="download-card"><div class="feature-icon">✧</div><div class="feature-title">Summary & insights</div><div class="feature-desc">Markdown report with summary, actions and decisions.</div></div>', unsafe_allow_html=True)
            st.download_button("Download Markdown", summary_md, f"{safe_title}_report.md", "text/markdown", use_container_width=True, key="dl_markdown")
        with c3:
            st.markdown('<div class="download-card"><div class="feature-icon">{ }</div><div class="feature-title">Portable data</div><div class="feature-desc">Analysis fields and transcript in JSON format.</div></div>', unsafe_allow_html=True)
            st.download_button("Download JSON", json.dumps(report, ensure_ascii=False, indent=2), f"{safe_title}_report.json", "application/json", use_container_width=True, key="dl_json")
    st.write("")
    cnew, chome = st.columns([1, 1], gap="medium")
    with cnew:
        if st.button("＋ Analyze another video", type="primary", use_container_width=True):
            st.session_state.page = "setup"
            st.session_state.last_error = None
            st.rerun()
    with chome:
        if st.button("Return to home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()


def _start_analysis_dispatch() -> None:
    # Called after rerun so the processing UI is already present before work begins.
    pending = st.session_state.pop("pending_run", None)
    if pending:
        run_pipeline(pending["source"], pending["language"], pending["include_visuals"], pending["interval"], pending["max_frames"])


def _run_pipeline_unlocked(source: str, language: str, include_visuals: bool = False, visual_interval_seconds: int = 60, max_visual_frames: int = 80) -> None:
    st.session_state.result = None
    st.session_state.chat_history = []
    st.session_state.pipeline_steps = {}
    st.session_state.last_error = None
    st.session_state.last_failed_step = None
    st.session_state.retry_source = source
    st.session_state.retry_language = language
    st.session_state.include_visuals = include_visuals
    st.session_state.visual_interval_seconds = visual_interval_seconds
    st.session_state.max_visual_frames = max_visual_frames
    st.session_state.visual_evidence = []

    status_box = st.status("Running analysis pipeline", expanded=True)
    current_step = "audio"
    try:
        with status_box:
            can_reuse_transcript = (
                st.session_state.prepared_source == source
                and st.session_state.prepared_language == language
                and st.session_state.prepared_transcript
                and st.session_state.prepared_chunks
            )

            if can_reuse_transcript:
                st.write("Reusing prepared transcript from the previous attempt...")
                chunks = st.session_state.prepared_chunks
                transcript = st.session_state.prepared_transcript
                update_step("audio", "done")
                update_step("transcript", "done")
            else:
                current_step = "audio"
                update_step("audio", "active")
                st.write("Preparing audio...")
                chunks = process_input(source)
                update_step("audio", "done")

                current_step = "transcript"
                update_step("transcript", "active")
                st.write("Transcribing audio...")
                transcription_progress = st.progress(0, text="Preparing transcription...")
                def report_transcription_progress(done: int, total: int) -> None:
                    fraction = done / max(total, 1)
                    transcription_progress.progress(
                        fraction,
                        text=f"Transcribed audio chunk {done}/{total}",
                    )
                transcript = transcribe_all(
                    chunks,
                    language,
                    source_id=source,
                    progress_callback=report_transcription_progress,
                )
                transcription_progress.empty()
                update_step("transcript", "done")
                st.session_state.prepared_source = source
                st.session_state.prepared_language = language
                st.session_state.prepared_chunks = chunks
                st.session_state.prepared_transcript = transcript
                st.session_state.prepared_analysis = None

            can_reuse_analysis = (
                st.session_state.prepared_source == source
                and st.session_state.prepared_language == language
                and st.session_state.prepared_analysis
            )

            if can_reuse_analysis:
                st.write("Reusing completed Groq analysis from the previous attempt...")
                analysis = st.session_state.prepared_analysis
                update_step("title", "done")
                update_step("summary", "done")
                update_step("extract", "done")
            else:
                current_step = "analysis"
                update_step("title", "active")
                update_step("summary", "active")
                update_step("extract", "active")
                st.write("Generating title, summary, action items, decisions, and questions...")
                try:
                    analysis = analyze_transcript(transcript)
                except Exception as exc:
                    if not is_rate_limit_error(exc):
                        raise
                    st.warning(
                        "Groq is still rate-limited. Completing this run with a local transcript-based fallback.",
                        icon=":material/warning:",
                    )
                    analysis = fallback_analysis(transcript)
                st.session_state.prepared_analysis = analysis
                update_step("title", "done")
                update_step("summary", "done")
                update_step("extract", "done")

            visual_evidence = []
            rag_corpus = transcript
            if not include_visuals:
                update_step("visual", "skipped")
            if include_visuals:
                current_step = "visual"
                update_step("visual", "active")
                if source.startswith("http://") or source.startswith("https://"):
                    st.warning("Visual analysis currently works with a local video file. YouTube visual downloading is not enabled to avoid unexpectedly downloading many gigabytes.")
                else:
                    if Path(source).suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
                        st.warning("Visual analysis requires a local video file (MP4/MOV/MKV/WEBM/AVI). Continuing with transcript-only RAG.")
                    else:
                        st.write("Sampling video frames and describing selected frames with Groq Vision...")
                        visual_evidence = analyze_local_video(source, interval_seconds=visual_interval_seconds, max_frames=max_visual_frames)
                    if visual_evidence:
                        visual_text = "\n\n".join(
                            f"[VISUAL FRAME {item['timestamp']}] {item['description']}"
                            for item in visual_evidence
                        )
                        rag_corpus += "\n\nVISUAL EVIDENCE\n" + visual_text
                st.session_state.visual_evidence = visual_evidence
                update_step("visual", "done")

            current_step = "rag"
            update_step("rag", "active")
            st.write("Building isolated chat index...")
            rag_chain = build_rag_chain(rag_corpus)
            update_step("rag", "done")

        st.session_state.result = {
            "source": source,
            "audio_chunks": [str(item) for item in chunks],
            "title": analysis["title"],
            "transcript": transcript,
            "summary": analysis["summary"],
            "action_items": analysis["action_items"],
            "key_decisions": analysis["key_decisions"],
            "open_questions": analysis["open_questions"],
            "rag_chain": rag_chain,
            "chunk_count": len(chunks),
            "language": language,
            "used_fallback": analysis.get("used_fallback", False),
            "visual_evidence": st.session_state.visual_evidence,
        }
        st.session_state.last_failed_step = None
        st.session_state.last_error = None
        st.session_state.page = "results"
        status_box.update(label="Analysis complete", state="complete", expanded=False)
        time.sleep(0.3)
        st.rerun()
    except Exception as exc:
        for key in [step[0] for step in PIPELINE_STEPS]:
            if st.session_state.pipeline_steps.get(key) == "active":
                st.session_state.pipeline_steps[key] = "error"
        st.session_state.last_error = _friendly_pipeline_error(exc)
        st.session_state.last_failed_step = current_step
        st.session_state.page = "analysis"
        status_box.update(label=f"Analysis failed during {current_step}", state="error", expanded=True)
        # Re-render the page so the failure card and retry action appear immediately.
        st.rerun()


def _friendly_pipeline_error(exc: Exception) -> str:
    """Keep long yt-dlp paths and ANSI escapes out of the UI; retain useful detail."""
    raw = str(exc)
    lowered = raw.lower()
    if "invalid js_runtimes format" in lowered:
        return (
            "The installed yt-dlp version received an invalid JavaScript runtime option. "
            "Replace utils/audio_processor.py with the updated version and restart Streamlit."
        )
    if (
        "requested format is not available" in lowered
        or "only images are available" in lowered
        or "challenge solving failed" in lowered
        or "signature solving failed" in lowered
        or "n challenge" in lowered
    ):
        return (
            "YouTube did not expose a usable audio-only format. In the activated .venv312 "
            'terminal run: python -m pip install --upgrade "yt-dlp[default]". Also verify '
            "Node.js v22+ or Deno v2.3+ is installed, then stop all Streamlit terminals "
            "and restart the app. If it still fails, test with a different public video."
        )
    if "winerror 32" in lowered or "unable to rename file" in lowered:
        return (
            "Windows locked a temporary download file, usually because the same source was "
            "being downloaded in another session. Stop other Streamlit instances and retry; "
            "the updated downloader writes each attempt to a unique folder."
        )
    compact = " ".join(raw.replace("\x1b", " ").split())
    return compact[:700] if compact else "Analysis failed. Check the terminal for the detailed error."


def run_pipeline(
    source: str,
    language: str,
    include_visuals: bool = False,
    visual_interval_seconds: int = 60,
    max_visual_frames: int = 80,
) -> None:
    """Serialized public entry point for one analysis run."""
    if not _PIPELINE_LOCK.acquire(blocking=False):
        st.session_state.last_error = (
            "Another analysis is already running in this app process. Wait for it to finish, "
            "then submit this video again. This prevents overlapping downloads."
        )
        st.session_state.last_failed_step = "pipeline"
        st.session_state.retry_source = source
        st.session_state.retry_language = language
        st.warning(st.session_state.last_error, icon=":material/hourglass_top:")
        return
    try:
        _run_pipeline_unlocked(
            source, language, include_visuals, visual_interval_seconds, max_visual_frames
        )
    finally:
        _PIPELINE_LOCK.release()




init_state()
render_theme_styles()
render_splash_once()
page = st.session_state.get("page", "home")
render_navbar(page)

if page == "home":
    render_home()
elif page == "setup":
    render_setup_page()
elif page == "analysis":
    render_analysis_page()
    _start_analysis_dispatch()
elif page == "results":
    render_results()
else:
    st.session_state.page = "home"
    st.rerun()
