# pyright: reportMissingImports=false
"""
gui_app.py — 메인 GUI 앱  (Neo-Brutalist Theme)
네이버 블로그 포스팅(상단) + 뉴스 기사 분석(하단, news_analyzer.py)
"""
import sys
import json
import time
import queue
import threading
import traceback
import re

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

try:
    from standalone_poster import (
        get_driver,
        ensure_logged_in,
        write_post,
    )
except ImportError:
    messagebox.showerror(
        "임포트 오류",
        "standalone_poster.py 파일을 찾을 수 없거나 임포트할 수 없습니다.\n"
        "같은 디렉토리에 해당 파일이 존재하는지 확인해 주세요."
    )
    sys.exit(1)

from news_analyzer import NewsAnalyzerSection
from config_manager import load_config, save_config
from thread_manager import ThreadManager
import gemini_service
import utils

try:
    from stock_report import StockReportSection
except ImportError:
    StockReportSection = None  # yfinance/matplotlib 미설치 시 탭 비활성

try:
    from industry_section import IndustrySectorSection
except ImportError:
    IndustrySectorSection = None

try:
    from investor_trade_section import InvestorTradeSection
except ImportError:
    InvestorTradeSection = None

# ── Gemini 모델 목록 (표시명 → API ID) ──────────────────────────────
GEMINI_MODELS = [
    ("Gemini 3.1 Flash Lite", "gemini-3.1-flash-lite"),
    ("Gemini 3 Flash",        "gemini-3.0-flash"),
    ("Gemini 3.5 Flash",      "gemini-3.5-flash"),
    ("Gemini 2.5 Flash",      "gemini-2.5-flash"),
    ("Gemini 2.5 Pro",        "gemini-2.5-pro"),
    ("Gemini 2 Flash",        "gemini-2.0-flash"),
    ("Gemini 2 Flash Lite",   "gemini-2.0-flash-lite"),
]
_MODEL_NAMES  = [name for name, _ in GEMINI_MODELS]
_NAME_TO_ID   = {name: mid  for name, mid  in GEMINI_MODELS}
_ID_TO_NAME   = {mid:  name for name, mid  in GEMINI_MODELS}
DEFAULT_MODEL = "gemini-3.1-flash-lite"


# ── 로그 스트림 리다이렉션 ──────────────────────────────────────────
class QueueWriteStream:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, string: str) -> None:
        if string.strip():
            self.q.put(f"{time.strftime('[%H:%M:%S] ')}{string.strip()}\n")
        else:
            self.q.put(string)

    def flush(self) -> None:
        pass


# ── 메인 GUI 클래스 ─────────────────────────────────────────────────
class NaverPosterGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("네이버 블로그 자동 포스터 (Gemini AI)")
        self.root.geometry("880x900")
        self.root.minsize(760, 740)

        # ── Neo-Brutalist Theme ──────────────────────
        self.bg_dark      = "#F5F0E8"   # Warm Off-White  (창·컨테이너 배경)
        self.bg_card      = "#FFFFFF"   # Pure White       (카드·섹션 배경)
        self.bg_input     = "#FFFFFF"   # 입력 필드 배경
        self.text_light   = "#FFFFFF"   # 밝은 텍스트 (검정·파랑 버튼 위)
        self.text_dark    = "#1A1A1A"   # 기본 텍스트 (검정)
        self.text_muted   = "#4A4A4A"   # 보조 텍스트
        self.primary      = "#1A1A1A"   # Primary Black (주요 버튼)
        self.accent       = "#FFCC00"   # Vivid Yellow (강조·호버)
        self.hover        = "#FFCC00"   # 호버 색 (Yellow)
        self.hover_dark   = "#E6B800"   # 진한 Yellow 호버 (yellow 버튼용)
        self.tertiary     = "#0055FF"   # Bauhaus Blue (분석 버튼)
        self.tertiary_hov = "#003DD6"   # 진한 Blue 호버
        self.error        = "#E63B2E"   # Signal Red
        self.gray         = "#4A4A4A"   # 비활성/작업중 상태
        self.border_color = "#1A1A1A"   # 테두리 (검정)
        self.btn_rss      = "#0055FF"   # RSS 분석 버튼 (=tertiary)
        # ────────────────────────────────────────────

        self.root.configure(bg=self.bg_dark)
        self.setup_styles()

        self.log_queue = queue.Queue()
        self.thread_manager = ThreadManager(self.root)

        self.create_widgets()
        self.load_and_populate_config()
        self.check_log_queue()

        sys.stdout = QueueWriteStream(self.log_queue)
        sys.stderr = QueueWriteStream(self.log_queue)

        self.loaded_html_content = ""
        self.loaded_plain_content = ""

        print("[시스템] 프로그램이 실행되었습니다. 설정 탭을 먼저 구성해 주세요.")

    # ──────────────────────────────────────────────
    # 스타일 설정
    # ──────────────────────────────────────────────
    def setup_styles(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("default")

        # Notebook
        self.style.configure("TNotebook",
            background=self.bg_dark, borderwidth=0)
        self.style.configure("TNotebook.Tab",
            background=self.bg_card,
            foreground=self.text_dark,
            padding=[22, 9],
            font=("맑은 고딕", 10, "bold"),
            borderwidth=2,
            lightcolor=self.border_color,
            darkcolor=self.border_color,
        )
        self.style.map("TNotebook.Tab",
            background=[("selected", self.accent)],
            foreground=[("selected", self.text_dark)],
        )

        # Scrollbar
        self.style.configure("Vertical.TScrollbar",
            background=self.gray,
            troughcolor=self.bg_dark,
            arrowcolor=self.text_light,
            borderwidth=0,
        )

        # Combobox
        self.style.configure("TCombobox",
            fieldbackground=self.bg_input,
            background=self.primary,
            foreground=self.text_dark,
            arrowcolor=self.text_dark,
            selectbackground=self.accent,
            selectforeground=self.text_dark,
            borderwidth=2,
        )
        self.style.map("TCombobox",
            fieldbackground=[("readonly", self.bg_input)],
            foreground=[("readonly", self.text_dark)],
            selectbackground=[("readonly", self.accent)],
        )

        # Dropdown 리스트 박스
        self.root.option_add("*TCombobox*Listbox.background",       self.bg_card)
        self.root.option_add("*TCombobox*Listbox.foreground",       self.text_dark)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", self.text_dark)
        self.root.option_add("*TCombobox*Listbox.font",             "맑은고딕 10")

    # ──────────────────────────────────────────────
    # 위젯 생성
    # ──────────────────────────────────────────────
    def create_widgets(self) -> None:
        # ── 헤더 (검정 바) ──
        header = tk.Frame(self.root, bg=self.primary, pady=10)
        header.pack(fill="x", side="top")

        tk.Label(
            header,
            text="NAVER BLOG AUTO POSTER",
            font=("맑은 고딕", 15, "bold"),
            bg=self.primary, fg=self.text_light,
        ).pack(side="left", padx=20)

        tk.Label(
            header,
            text="Powered by Gemini",
            font=("맑은 고딕", 9, "italic"),
            bg=self.primary, fg=self.accent,
        ).pack(side="left", padx=4)

        # ── 글로벌 하단 로그 콘솔 ──
        self.console_expanded = True
        self.console_frame = tk.LabelFrame(
            self.root,
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=8, pady=6,
        )
        self.console_frame.pack(fill="x", side="bottom", padx=16, pady=(0, 10))

        # 콘솔 헤더 (제목 + 접기/펼치기 버튼)
        header_frame = tk.Frame(self.console_frame, bg=self.bg_card)
        lbl = tk.Label(
            header_frame,
            text="  실시간 작업 로그  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        )
        lbl.pack(side="left")

        self.toggle_btn = tk.Button(
            header_frame,
            text="[▼ 콘솔 접기]",
            font=("맑은 고딕", 8, "bold"),
            bg=self.accent, fg=self.text_dark,
            activebackground=self.hover_dark, activeforeground=self.text_dark,
            bd=1, relief="solid", cursor="hand2",
            padx=6, pady=1,
            command=self.toggle_console,
        )
        self.toggle_btn.pack(side="left", padx=10)
        self.console_frame.configure(labelwidget=header_frame)

        self.log_text = scrolledtext.ScrolledText(
            self.console_frame,
            height=6,
            bg=self.primary, fg=self.accent,
            insertbackground=self.accent,
            font=("Consolas", 9),
            bd=2, relief="solid",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

        # ── 메인 탭 노트북 ──
        self.notebook = ttk.Notebook(self.root, style="TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=16, pady=10)

        # Tab 1: 블로그 발행
        self.tab_blog = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_blog, text="  📝 블로그 발행  ")

        # Tab 2: 뉴스 분석
        self.tab_news = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_news, text="  📰 뉴스 분석  ")

        # Tab 3: 주식 리포트
        self.tab_stock = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_stock, text="  📈 주식 리포트  ")

        # Tab 4: 종목 탐색
        self.tab_explorer = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_explorer, text="  🔍 종목 탐색  ")

        # Tab 5: 설정
        self.tab_settings = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_settings, text="  ⚙️ 설정  ")

        self.build_blog_tab()
        self.build_news_tab()
        self.build_stock_tab()
        self.build_explorer_tab()
        self.build_settings_tab()

    def toggle_console(self) -> None:
        if self.console_expanded:
            self.log_text.pack_forget()
            self.toggle_btn.configure(text="[▲ 콘솔 열기]")
            self.console_expanded = False
        else:
            self.log_text.pack(fill="both", expand=True)
            self.toggle_btn.configure(text="[▼ 콘솔 접기]")
            self.console_expanded = True

    # ──────────────────────────────────────────────
    # 블로그 발행 탭
    # ──────────────────────────────────────────────
    def build_blog_tab(self) -> None:
        container = tk.Frame(self.tab_blog, bg=self.bg_dark)
        container.pack(fill="both", expand=True, padx=8, pady=6)
        
        # Left Panel (Controls)
        left_panel = tk.Frame(container, bg=self.bg_dark, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 8))
        left_panel.pack_propagate(False) # 고정 너비
        
        # AI Draft Generator
        ai_frame = tk.LabelFrame(
            left_panel,
            text="  🤖 AI 글 생성 주제  ",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=8, pady=8,
        )
        ai_frame.pack(fill="x", pady=(0, 8))
        
        self.prompt_text = tk.Text(
            ai_frame,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            font=("맑은 고딕", 9),
            bd=2, relief="solid",
            height=10,
        )
        self.prompt_text.pack(fill="x", pady=(0, 6))
        self.prompt_text.insert(
            "1.0",
            "요즘 뜨고 있는 유용한 AI 코딩 툴의 트렌드와 장점을 소개하는 글을 써줘.",
        )
        
        self.ai_gen_btn = tk.Button(
            ai_frame,
            text="🤖 AI 초안 생성",
            font=("맑은 고딕", 9, "bold"),
            bg=self.btn_rss, fg=self.text_light,
            activebackground=self.tertiary_hov, activeforeground=self.text_light,
            bd=0, relief="flat", cursor="hand2",
            padx=10, pady=8,
            command=self.start_ai_generation_thread,
        )
        self.ai_gen_btn.pack(fill="x")
        self.ai_gen_btn.bind("<Enter>", lambda e: self._on_hover(e, self.tertiary_hov))
        self.ai_gen_btn.bind("<Leave>", lambda e: self._on_hover(e, self.btn_rss))
        
        # HTML File Importer
        html_frame = tk.LabelFrame(
            left_panel,
            text="  📂 HTML 파일 가져오기  ",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=8, pady=8,
        )
        html_frame.pack(fill="x")
        
        tk.Label(
            html_frame,
            text="주식 리포트 탭 [📤 발행] 버튼으로\n자동 전달, 또는 파일을 직접 선택.",
            font=("맑은 고딕", 8),
            bg=self.bg_card, fg=self.text_muted, justify="left",
        ).pack(fill="x", pady=(0, 6))
        
        self.import_btn = tk.Button(
            html_frame,
            text="📂 기존 HTML 파일 열기",
            font=("맑은 고딕", 9, "bold"),
            bg=self.accent, fg=self.text_dark,
            activebackground=self.hover_dark, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2",
            padx=10, pady=8,
            command=self.open_html_file,
        )
        self.import_btn.pack(fill="x")
        self.import_btn.bind("<Enter>", lambda e: self._on_hover(e, self.hover_dark))
        self.import_btn.bind("<Leave>", lambda e: self._on_hover(e, self.accent))
        
        # Right Panel (Editor & Publisher)
        right_panel = tk.LabelFrame(
            container,
            text="  📝 발행 대기 콘텐츠  ",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=10, pady=8,
        )
        right_panel.pack(side="right", fill="both", expand=True)

        # HTML 리포트 로드 시 안내 레이블
        self.html_notice_lbl = tk.Label(
            right_panel,
            text="",
            font=("맑은 고딕", 8), bg=self.bg_card, fg="#555555",
            anchor="w", wraplength=480, justify="left",
        )
        self.html_notice_lbl.pack(fill="x", pady=(0, 4))

        # Title Field
        tk.Label(
            right_panel, text="제목:",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        ).pack(anchor="w", pady=(0, 2))

        self.blog_title_entry = tk.Entry(
            right_panel,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            bd=2, relief="solid",
            font=("맑은 고딕", 10, "bold"),
        )
        self.blog_title_entry.pack(fill="x", pady=(0, 8))
        self.blog_title_entry.insert(0, "[초안 제목이 이곳에 표시됩니다]")

        # Content Field
        tk.Label(
            right_panel, text="본문 내용 (미리보기 — 실제 발행 시 표·이미지 포함 HTML 원본이 전송됩니다):",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        ).pack(anchor="w", pady=(0, 2))

        self.blog_content_text = scrolledtext.ScrolledText(
            right_panel,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            font=("맑은 고딕", 10),
            bd=2, relief="solid",
        )
        self.blog_content_text.pack(fill="both", expand=True, pady=(0, 8))
        self.blog_content_text.insert(
            "1.0",
            "[초안 본문이 이곳에 표시됩니다.]",
        )
        
        # Hashtags Field
        tk.Label(
            right_panel, text="해시태그 (12~15개 문장 핵심 키워드 자동 선정):",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        ).pack(anchor="w", pady=(0, 2))
        
        self.blog_tags_entry = tk.Entry(
            right_panel,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            bd=2, relief="solid",
            font=("맑은 고딕", 9),
        )
        self.blog_tags_entry.pack(fill="x", pady=(0, 10))
        self.blog_tags_entry.insert(0, "#주식시황 #증시분석")
        
        # Post Button
        self.post_btn = tk.Button(
            right_panel,
            text="🚀  네이버 블로그 포스팅 시작  🚀",
            font=("맑은 고딕", 11, "bold"),
            bg=self.primary, fg=self.text_light,
            activebackground=self.accent, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2",
            padx=20, pady=12,
            command=self.start_posting_process_thread,
        )
        self.post_btn.pack(fill="x")
        self.post_btn.bind("<Enter>", lambda e: self._on_hover(e, self.accent))
        self.post_btn.bind("<Leave>", lambda e: self._on_hover(e, self.primary))

    # ──────────────────────────────────────────────
    # 뉴스 분석 탭
    # ──────────────────────────────────────────────
    def build_news_tab(self) -> None:
        container = tk.Frame(self.tab_news, bg=self.bg_dark)
        container.pack(fill="both", expand=True, padx=8, pady=6)

        # ── 뉴스 기사 분석 (news_analyzer.py) ──
        self.news_section = NewsAnalyzerSection(self.root, self._theme_dict(), self.thread_manager)
        self.news_section.build(container)
        # 분석 완료 시 블로그 탭으로 자동 전달 콜백 등록
        self.news_section._on_blog_ready_cb = self._load_report_to_blog

    # ──────────────────────────────────────────────
    # 테마 딕셔너리 (섹션 모듈에 전달)
    # ──────────────────────────────────────────────
    def _theme_dict(self) -> dict:
        return {
            "bg_card":      self.bg_card,
            "bg_input":     self.bg_input,
            "text_light":   self.text_light,
            "text_dark":    self.text_dark,
            "text_muted":   self.text_muted,
            "accent":       self.accent,
            "hover":        self.hover,
            "hover_dark":   self.hover_dark,
            "btn_rss":      self.btn_rss,
            "tertiary":     self.tertiary,
            "tertiary_hov": self.tertiary_hov,
            "primary":      self.primary,
            "border_color": self.border_color,
        }

    # ──────────────────────────────────────────────
    # 주식 리포트 탭
    # ──────────────────────────────────────────────
    def build_stock_tab(self) -> None:
        container = tk.Frame(self.tab_stock, bg=self.bg_dark)
        container.pack(fill="both", expand=True, padx=8, pady=6)

        if StockReportSection is None:
            tk.Label(
                container,
                text=("⚠️ 주식 리포트 기능을 사용하려면 패키지 설치가 필요합니다.\n\n"
                      "    pip install yfinance matplotlib"),
                font=("맑은 고딕", 11, "bold"),
                bg=self.bg_dark, fg=self.error, justify="left",
            ).pack(pady=40)
            return

        self.stock_section = StockReportSection(self.root, self._theme_dict())
        self.stock_section.build(container)
        # 리포트 완료 시 블로그 탭으로 자동 전달 콜백 등록
        self.stock_section._on_blog_ready_cb = self._load_report_to_blog

    # ──────────────────────────────────────────────
    # 종목 탐색 탭
    # ──────────────────────────────────────────────
    def build_explorer_tab(self) -> None:
        container = tk.Frame(self.tab_explorer, bg=self.bg_dark)
        container.pack(fill="both", expand=True, padx=8, pady=6)

        if IndustrySectorSection is not None:
            self.industry_section = IndustrySectorSection(
                self.root, self._theme_dict(), self.stock_section,
                main_notebook=self.notebook, sub_notebook=None
            )
            self.industry_section.build(container)

    # ──────────────────────────────────────────────
    # 설정 탭
    # ──────────────────────────────────────────────
    def build_settings_tab(self) -> None:
        sc = tk.Frame(self.tab_settings, bg=self.bg_dark)
        sc.pack(fill="both", expand=True, padx=16, pady=12)

        # ── Gemini 모델 선택 ──
        model_frame = tk.LabelFrame(
            sc,
            text="  Gemini 모델 선택  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=15, pady=14,
        )
        model_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            model_frame,
            text="사용 모델:",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.model_var = tk.StringVar(value=_ID_TO_NAME.get(DEFAULT_MODEL, _MODEL_NAMES[0]))
        self.model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.model_var,
            values=_MODEL_NAMES,
            state="readonly",
            font=("맑은 고딕", 10),
            width=30,
        )
        self.model_combo.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        tk.Label(
            model_frame,
            text="※ 기본값: Gemini 3.1 Flash Lite",
            font=("맑은 고딕", 8, "italic"),
            bg=self.bg_card, fg=self.text_muted,
        ).grid(row=1, column=1, sticky="w", padx=10)

        # ── API Key ──
        api_frame = tk.LabelFrame(
            sc,
            text="  Google Gemini API 설정  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=15, pady=14,
        )
        api_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            api_frame, text="Gemini API Key:",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.api_entry = tk.Entry(
            api_frame, width=50,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            bd=2, relief="solid",
            font=("Consolas", 10), show="*",
        )
        self.api_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        self.api_visible = False
        self.api_toggle_btn = tk.Button(
            api_frame, text="보기",
            font=("맑은 고딕", 8, "bold"),
            bg=self.accent, fg=self.text_dark,
            activebackground=self.hover_dark, activeforeground=self.text_dark,
            bd=2, relief="solid", cursor="hand2",
            padx=8, pady=2,
            command=self.toggle_api_visibility,
        )
        self.api_toggle_btn.grid(row=0, column=2, padx=5, pady=5)

        # 네이버 계정
        naver_frame = tk.LabelFrame(
            sc,
            text="  네이버 계정 설정 (DPAPI 암호화 저장)  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=15, pady=14,
        )
        naver_frame.pack(fill="x", pady=(0, 10))

        for row, (label_text, attr) in enumerate([
            ("네이버 ID:", "id_entry"),
            ("네이버 PW:", "pw_entry"),
        ]):
            tk.Label(
                naver_frame, text=label_text,
                font=("맑은 고딕", 10, "bold"),
                bg=self.bg_card, fg=self.text_dark,
            ).grid(row=row, column=0, sticky="w", pady=5)

            entry = tk.Entry(
                naver_frame, width=50,
                bg=self.bg_input, fg=self.text_dark,
                insertbackground=self.text_dark,
                bd=2, relief="solid",
                font=("맑은 고딕", 10),
                show="*" if row == 1 else "",
            )
            entry.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            setattr(self, attr, entry)

        self.save_settings_btn = tk.Button(
            sc,
            text="💾  설정 안전하게 암호화 저장",
            font=("맑은 고딕", 11, "bold"),
            bg=self.primary, fg=self.text_light,
            activebackground=self.accent, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2",
            padx=20, pady=13,
            command=self.save_gui_config,
        )
        self.save_settings_btn.pack(fill="x", pady=10)
        self.save_settings_btn.bind("<Enter>", lambda e: self._on_hover(e, self.accent))
        self.save_settings_btn.bind("<Leave>", lambda e: self._on_hover(e, self.primary))

    # ──────────────────────────────────────────────
    # 네이버 포스팅
    # ──────────────────────────────────────────────
    def start_posting_process_thread(self) -> None:
        title = self.blog_title_entry.get().strip()
        content = self.blog_content_text.get("1.0", "end").strip()
        tags = self.blog_tags_entry.get().strip()

        if not title or not content:
            messagebox.showwarning("입력 오류", "발행할 제목과 본문을 입력해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("naver_id") or not cfg.get("naver_pw"):
            messagebox.showwarning("설정 오류", "네이버 ID/PW가 설정되지 않았습니다. 설정 탭에서 입력해 주세요.")
            return

        # HTML 리포트 로드 여부에 따라 발행 방식 결정
        loaded_html = getattr(self, "loaded_html_content", "")
        if loaded_html:
            # HTML 리포트 모드: 항상 원본 HTML(표·이미지 포함) 발행
            is_html = True
            full_content = loaded_html
        else:
            # AI 초안 모드: 에디터 텍스트 그대로 발행
            is_html = bool(re.search(r'<(?:html|body|div|table|p|h[1-6]|ul|ol|br\s*/?)[\s>]', content, re.IGNORECASE))
            full_content = content
        
        if is_html:
            # HTML 내 로컬 이미지 절대 경로를 base64 데이터로 치환
            print("[클립보드] HTML 이미지 base64 변환을 시작합니다...")
            full_content = utils.resolve_html_images_to_base64(full_content)
            print("✅ HTML 이미지 변환 완료")

        self._reset_button(self.post_btn, "작업 진행 중... ⏳", self.gray)
        self.post_btn.configure(state="disabled")

        self.thread_manager.run_async(
            self.run_posting, cfg, title, full_content, tags
        )

    def run_posting(self, cfg: dict, title: str, content: str, tags: str = "") -> None:
        driver = None
        try:
            print("\n" + "=" * 60)
            print("🚀 포스팅 작업을 시작합니다.")
            print(f"📝 제목: {title}")
            print(f"📝 본문 길이: 약 {len(content)}자")
            print("=" * 60)

            print("[셀레늄] 크롬 드라이버를 기동합니다...")
            driver = get_driver(cfg["naver_id"])
            ensure_logged_in(driver, cfg["naver_id"], cfg["naver_pw"])

            print("[셀레늄] 네이버 글쓰기 모듈을 호출합니다...")
            published_url = write_post(driver, cfg["naver_id"], title, content, tags)

            print(f"\n🎉 포스팅 성공!\n🔗 포스트 주소: {published_url}\n" + "=" * 60)
            self.root.after(
                0,
                lambda: messagebox.showinfo("포스팅 완료", f"포스팅 성공!\n주소: {published_url}"),
            )

        except Exception as e:
            err = str(e)
            print(f"\n❌ 오류 발생:\n{err}\n{traceback.format_exc()}")
            self.root.after(
                0,
                lambda: messagebox.showerror("포스팅 실패", f"에러가 발생했습니다:\n{err}"),
            )

        finally:
            if driver:
                try:
                    driver.quit()
                    print("[셀레늄] 브라우저 세션 종료.")
                except Exception:
                    pass
            self.root.after(
                0,
                lambda: self._reset_button(
                    self.post_btn, "🚀  네이버 블로그 포스팅 시작  🚀", self.primary
                ),
            )

    def start_ai_generation_thread(self) -> None:
        prompt_val = self.prompt_text.get("1.0", "end").strip()
        if not prompt_val:
            messagebox.showwarning("입력 오류", "블로그 주제 또는 프롬프트를 입력해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "Gemini API Key가 설정되지 않았습니다. 설정 탭에서 입력해 주세요.")
            return

        self.ai_gen_btn.configure(state="disabled", text="생성 중... ⏳", bg=self.gray)
        
        def run():
            self.loaded_html_content = ""
            self.loaded_plain_content = ""
            print("\n" + "=" * 60)
            print("[AI 생성] Gemini API로 블로그 콘텐츠 생성을 요청합니다...")
            model_id = cfg.get("gemini_model", DEFAULT_MODEL)
            title, content = gemini_service.generate_blog_content(cfg["gemini_api_key"], prompt_val, model_id)
            print(f"✅ AI 콘텐츠 초안 생성 완료! 제목: {title}")
            
            # 해시태그 생성 (12~15개)
            print("[AI 태그] 본문 기반 해시태그 12~15개 선정을 시작합니다...")
            tags = gemini_service.generate_hashtags(cfg["gemini_api_key"], model_id, content)
            print(f"✅ 해시태그 생성 완료: {tags}")
            return title, content, tags

        def success(result):
            title, content, tags = result
            self.blog_title_entry.delete(0, "end")
            self.blog_title_entry.insert(0, title)
            self.blog_content_text.delete("1.0", "end")
            self.blog_content_text.insert("1.0", content)
            self.blog_tags_entry.delete(0, "end")
            self.blog_tags_entry.insert(0, tags)
            self.ai_gen_btn.configure(state="normal", text="🤖 AI 초안 생성", bg=self.btn_rss)
            print("[시스템] 에디터 창에 생성된 내용을 로드했습니다.")

        def failure(e):
            self.ai_gen_btn.configure(state="normal", text="🤖 AI 초안 생성", bg=self.btn_rss)
            print(f"❌ AI 생성 실패: {e}")
            messagebox.showerror("AI 생성 실패", f"에러가 발생했습니다:\n{e}")

        self.thread_manager.run_async(run, on_success=success, on_failure=failure)

    def open_html_file(self) -> None:
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="기존 발행된 HTML 파일 선택",
            filetypes=[("HTML Files", "*.html"), ("All Files", "*.*")]
        )
        if not file_path:
            return
        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "해시태그 분석을 위해 Gemini API Key가 필요합니다. 설정 탭에서 입력해 주세요.")
            return
        self.import_btn.configure(state="disabled", text="불러오는 중... ⏳", bg=self.gray)
        
        def run():
            self._do_load_html_data(file_path, cfg)

        def success(result):
            self.import_btn.configure(state="normal", text="📂 기존 HTML 파일 열기", bg=self.accent)

        def failure(e):
            self.import_btn.configure(state="normal", text="📂 기존 HTML 파일 열기", bg=self.accent)
            messagebox.showerror("HTML 로드 실패", f"에러가 발생했습니다:\n{e}")

        self.thread_manager.run_async(run, on_success=success, on_failure=failure)

    def _load_report_to_blog(self, file_path: str) -> None:
        """주식 리포트 탭 [📤 발행] 버튼에서 자동 호출. 블로그 탭으로 전환 후 HTML 로드."""
        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "해시태그 분석을 위해 Gemini API Key가 필요합니다. 설정 탭에서 입력해 주세요.")
            return
        # 블로그 탭(인덱스 0)으로 전환
        self.notebook.select(0)
        self.import_btn.configure(state="disabled", text="리포트 불러오는 중... ⏳", bg=self.gray)

        def run():
            self._do_load_html_data(file_path, cfg)

        def success(result):
            self.import_btn.configure(state="normal", text="📂 기존 HTML 파일 열기", bg=self.accent)

        def failure(e):
            self.import_btn.configure(state="normal", text="📂 기존 HTML 파일 열기", bg=self.accent)
            messagebox.showerror("HTML 로드 실패", f"에러가 발생했습니다:\n{e}")

        self.thread_manager.run_async(run, on_success=success, on_failure=failure)

    def _do_load_html_data(self, file_path: str, cfg: dict) -> None:
        """HTML 파일을 읽어 평문 미리보기를 에디터에, 원본 HTML을 내부에 보관한다."""
        import os
        print("\n" + "=" * 60)
        print(f"📂 HTML 파일 읽는 중: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 기존 태그 박스 제거 (중복 삽입 방지)
        html_content = re.sub(
            r'<div[^>]*>\s*<h3[^>]*>#\s*태그</h3>.*?</div>',
            '',
            html_content,
            flags=re.DOTALL | re.IGNORECASE
        )

        _, plain_content = utils.parse_html_report(html_content)
        
        # 제목 생성 (2026년 6월 10일 형식 + 핵심 어휘, 2/3 길이)
        print("[AI 제목] 본문에서 블로그 제목 생성 시작...")
        model_id = cfg.get("gemini_model", DEFAULT_MODEL)
        title = gemini_service.generate_report_title(cfg["gemini_api_key"], model_id, plain_content)
        print(f"✅ AI 제목 생성 완료! 제목: {title} / 본문: 약 {len(plain_content)}자")

        # 해시태그 생성 (12~15개)
        print("[AI 태그] 본문에서 해시태그 선정 시작...")
        tags = gemini_service.generate_hashtags(cfg["gemini_api_key"], model_id, plain_content)
        print(f"✅ 해시태그 선정 완료: {tags}")

        # 평문 미리보기에도 해시태그 추가
        plain_content_with_tags = f"{plain_content}\n\n[태그]\n{tags}"

        # HTML 내의 H1 제목을 생성된 AI 제목으로 대체
        html_content = re.sub(r'<h1>.*?</h1>', f'<h1>📰 {title}</h1>', html_content, count=1, flags=re.IGNORECASE)

        # 해시태그 HTML 생성 및 본문 하단에 삽입
        tag_list = tags.split()
        tag_html = " ".join(f"<span style='display:inline-block; background:#1A1A1A; color:#FFCC00; padding:3px 8px; margin:3px 4px 3px 0; font-size:12px; border-radius:3px;'>{t}</span>" for t in tag_list)
        tags_box = f"""
<div style="background:#fff; border:3px solid #1A1A1A; padding:14px 18px; margin-top:24px; margin-bottom:20px;">
  <h3 style="font-size:16px; font-weight:bold; margin-top:0; margin-bottom:10px;"># 태그</h3>
  {tag_html}
</div>
"""
        if "</body>" in html_content:
            html_content = html_content.replace("</body>", f"{tags_box}\n</body>")
        else:
            html_content += tags_box

        # 이미지 상대 경로 → 절대 경로 치환 (발행용 HTML에만 적용)
        base_dir = os.path.dirname(file_path)
        def make_abs_src(match):
            img_tag = match.group(0)
            src_m = re.search(r'src=["\'](.*?)["\']', img_tag, re.IGNORECASE)
            if not src_m:
                return img_tag
            src = src_m.group(1)
            if src.startswith("data:") or os.path.isabs(src):
                return img_tag
            abs_path = os.path.abspath(os.path.join(base_dir, src)).replace("\\", "/")
            return re.sub(r'src=["\'](.*?)["\']', lambda m: f'src="{abs_path}"', img_tag, flags=re.IGNORECASE)

        html_for_post = re.sub(r'<img[^>]+>', make_abs_src, html_content, flags=re.IGNORECASE)

        # 발행용 HTML 보관 (에디터에는 평문 표시)
        self.loaded_html_content = html_for_post

        notice = (f"📄 {os.path.basename(file_path)}  |  "
                  "발행 시 표·그래프 포함 원본 HTML이 전송됩니다.")

        def update_gui():
            self.blog_title_entry.delete(0, "end")
            self.blog_title_entry.insert(0, title)
            self.blog_content_text.delete("1.0", "end")
            self.blog_content_text.insert("1.0", plain_content_with_tags)   # 평문 미리보기 (태그 포함)
            self.blog_tags_entry.delete(0, "end")
            self.blog_tags_entry.insert(0, tags)
            self.html_notice_lbl.configure(text=notice)
            print("[시스템] 평문 미리보기 및 태그 로드 완료.")

        self.root.after(0, update_gui)

    # ──────────────────────────────────────────────
    # 공통 헬퍼
    # ──────────────────────────────────────────────
    def _on_hover(self, event, color: str) -> None:
        if event.widget["state"] != "disabled":
            event.widget["background"] = color

    def _reset_button(self, btn: tk.Button, text: str, bg: str) -> None:
        btn.configure(state="normal", text=text, bg=bg)

    def toggle_api_visibility(self) -> None:
        if self.api_visible:
            self.api_entry.configure(show="*")
            self.api_toggle_btn.configure(text="보기")
            self.api_visible = False
        else:
            self.api_entry.configure(show="")
            self.api_toggle_btn.configure(text="숨기기")
            self.api_visible = True

    def load_and_populate_config(self) -> None:
        try:
            cfg = load_config()
            self.api_entry.insert(0, cfg.get("gemini_api_key", ""))
            self.id_entry.insert(0, cfg.get("naver_id", ""))
            self.pw_entry.insert(0, cfg.get("naver_pw", ""))
            saved_model_id = cfg.get("gemini_model", DEFAULT_MODEL)
            self.model_var.set(_ID_TO_NAME.get(saved_model_id, _MODEL_NAMES[0]))
        except Exception as e:
            print(f"[설정 로드 오류] {e}")

    def save_gui_config(self) -> None:
        cfg = {
            "gemini_api_key": self.api_entry.get().strip(),
            "naver_id":       self.id_entry.get().strip(),
            "naver_pw":       self.pw_entry.get().strip(),
            "gemini_model":   _NAME_TO_ID.get(self.model_var.get(), DEFAULT_MODEL),
        }
        if not all(cfg.values()):
            messagebox.showwarning("입력 오류", "모든 항목을 입력해 주세요.")
            return
        try:
            save_config(cfg)
            messagebox.showinfo("저장 완료", "설정이 암호화(DPAPI)되어 저장되었습니다.")
            print("[시스템] 설정 저장 완료.")
        except Exception as e:
            messagebox.showerror("저장 오류", f"저장 중 오류:\n{e}")

    def check_log_queue(self) -> None:
        while True:
            try:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except queue.Empty:
                break
        self.root.after(100, self.check_log_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = NaverPosterGUI(root)
    root.mainloop()
