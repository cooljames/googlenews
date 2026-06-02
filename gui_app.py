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
from google import genai
from google.genai import types

try:
    from standalone_poster import (
        load_config,
        save_config,
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

        self.create_widgets()
        self.load_and_populate_config()
        self.check_log_queue()

        sys.stdout = QueueWriteStream(self.log_queue)
        sys.stderr = QueueWriteStream(self.log_queue)

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
        header.pack(fill="x")

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

        self.notebook = ttk.Notebook(self.root, style="TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=16, pady=10)

        self.tab_post = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_post, text="  📝 글쓰기 (Post)  ")

        self.tab_settings = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_settings, text="  ⚙️ 설정 (Settings)  ")

        self.build_post_tab()
        self.build_settings_tab()

    # ──────────────────────────────────────────────
    # 글쓰기 탭
    # ──────────────────────────────────────────────
    def build_post_tab(self) -> None:
        container = tk.Frame(self.tab_post, bg=self.bg_dark)
        container.pack(fill="both", expand=True, padx=8, pady=6)

        # ── [1] 블로그 글 생성 주제 ──
        prompt_frame = tk.LabelFrame(
            container,
            text="  블로그 글 생성 주제 (프롬프트 입력)  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=10, pady=8,
        )
        prompt_frame.pack(fill="x", pady=(0, 6))

        self.prompt_text = tk.Text(
            prompt_frame,
            height=4,
            bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark,
            font=("맑은 고딕", 10),
            bd=2, relief="solid",
            padx=6, pady=6,
        )
        self.prompt_text.pack(fill="x")
        self.prompt_text.insert(
            "1.0",
            "요즘 뜨고 있는 유용한 AI 코딩 툴의 트렌드와 장점을 소개하는 글을 써줘.",
        )

        # ── [2] 네이버 포스팅 버튼 ──
        self.post_btn = tk.Button(
            container,
            text="🤖  AI 글 생성 및 네이버 포스팅 시작  🚀",
            font=("맑은 고딕", 11, "bold"),
            bg=self.primary, fg=self.text_light,
            activebackground=self.accent, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2",
            padx=20, pady=12,
            command=self.start_posting_process_thread,
        )
        self.post_btn.pack(fill="x", pady=6)
        self.post_btn.bind("<Enter>", lambda e: self._on_hover(e, self.accent))
        self.post_btn.bind("<Leave>", lambda e: self._on_hover(e, self.primary))

        # ── [3] 구분선 ──
        tk.Frame(container, bg=self.border_color, height=3).pack(fill="x", pady=8)

        # ── [4] 뉴스 기사 분석 (news_analyzer.py) ──
        theme = {
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
        self.news_section = NewsAnalyzerSection(self.root, theme)
        self.news_section.build(container)

        # ── [5] 로그 창 ──
        log_frame = tk.LabelFrame(
            container,
            text="  실시간 작업 로그 (Logs)  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid",
            padx=8, pady=6,
        )
        log_frame.pack(fill="both", expand=True, pady=(6, 0))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=7,
            bg=self.primary, fg=self.accent,
            insertbackground=self.accent,
            font=("Consolas", 9),
            bd=2, relief="solid",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

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
        prompt_val = self.prompt_text.get("1.0", "end").strip()
        if not prompt_val:
            messagebox.showwarning("입력 오류", "블로그 주제 또는 프롬프트를 입력해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "Gemini API Key가 설정되지 않았습니다.")
            return
        if not cfg.get("naver_id") or not cfg.get("naver_pw"):
            messagebox.showwarning("설정 오류", "네이버 ID/PW가 설정되지 않았습니다.")
            return

        self._reset_button(self.post_btn, "작업 진행 중... ⏳", self.gray)
        self.post_btn.configure(state="disabled")

        threading.Thread(
            target=self.run_posting, args=(cfg, prompt_val), daemon=True
        ).start()

    def run_posting(self, cfg: dict, prompt_text: str) -> None:
        driver = None
        try:
            print("\n" + "=" * 60)
            print("🚀 포스팅 작업을 시작합니다.")
            print("[AI 생성] Gemini API로 블로그 콘텐츠 생성을 요청합니다...")

            model_id = cfg.get("gemini_model", DEFAULT_MODEL)
            title, content = self.generate_blog_content(cfg["gemini_api_key"], prompt_text, model_id)
            print(f"✅ AI 콘텐츠 생성 완료! 제목: {title} / 본문: 약 {len(content)}자")
            print("=" * 60)

            print("[셀레늄] 크롬 드라이버를 기동합니다...")
            driver = get_driver(cfg["naver_id"])
            ensure_logged_in(driver, cfg["naver_id"], cfg["naver_pw"])

            print("[셀레늄] 네이버 글쓰기 모듈을 호출합니다...")
            published_url = write_post(driver, cfg["naver_id"], title, content)

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
                    self.post_btn, "🤖  AI 글 생성 및 네이버 포스팅 시작  🚀", self.primary
                ),
            )

    def generate_blog_content(self, api_key: str, prompt_text: str, model_id: str = DEFAULT_MODEL):
        client = genai.Client(api_key=api_key)
        system_instruction = """
당신은 네이버 블로그 포스팅을 전문으로 하는 지식이 풍부하고 유려한 에디터입니다.
사용자가 제공하는 주제/프롬프트에 맞추어 전문적이면서도 친근한 어투로 한국어 글을 작성하세요.
문단 구분을 확실하게 하여 가독성을 높여 주시기 바랍니다.

반드시 아래 JSON 스키마 형식으로만 응답하며, 코드 블록 없이 순수 JSON만 출력하세요.

{
  "title": "블로그 포스트 제목",
  "content": "풍부하고 상세한 본문 내용 (단락 구분은 \\n 활용)"
}
"""
        response = client.models.generate_content(
            model=model_id,
            contents=prompt_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        raw = self._clean_json(response.text or "")
        try:
            data = json.loads(raw)
            return data.get("title", f"포스트: {prompt_text[:15]}..."), data.get("content", raw)
        except Exception as json_err:
            print(f"[경고] JSON 파싱 폴백: {json_err}")
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if lines:
                return lines[0].replace("#", "").replace('"', "").strip(), "\n\n".join(lines[1:])
            return f"포스트: {prompt_text[:15]}...", raw

    # ──────────────────────────────────────────────
    # 공통 헬퍼
    # ──────────────────────────────────────────────
    def _on_hover(self, event, color: str) -> None:
        if event.widget["state"] != "disabled":
            event.widget["background"] = color

    def _reset_button(self, btn: tk.Button, text: str, bg: str) -> None:
        btn.configure(state="normal", text=text, bg=bg)

    def _clean_json(self, raw: str) -> str:
        return re.sub(
            r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.IGNORECASE
        ).strip()

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
