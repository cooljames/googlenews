# pyright: reportMissingImports=false
import os
import sys
import json
import time
import queue
import threading
import traceback
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# google-genai SDK
from google import genai
from google.genai import types

# Import functions from standalone_poster.py
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

# --- Thread-Safe Queue Write Stream for Redirection ---
class QueueWriteStream:
    def __init__(self, q, prefix=""):
        self.q = q
        self.prefix = prefix

    def write(self, string):
        if string.strip():
            # Add timestamps for utility
            timestamp = time.strftime("[%H:%M:%S] ")
            self.q.put(f"{timestamp}{string.strip()}\n")
        else:
            self.q.put(string)

    def flush(self):
        pass

class NaverPosterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("네이버 블로그 자동 포스터 (Gemini AI)")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)

        # Style colors (Dark Green Premium Theme)
        self.bg_dark = "#0c1b12"       # Deep green background
        self.bg_card = "#14291c"       # Medium card background
        self.bg_input = "#08120c"      # Near-black input background
        self.text_light = "#e8f5e9"    # Pale green text
        self.text_muted = "#a5d6a7"    # Muted green text
        self.primary = "#248c51"       # Primary green buttons
        self.hover = "#2fa563"         # Hover green
        self.accent = "#1d5736"        # Deep primary accent
        self.border_color = "#223f2d"  # Green-grey border color

        # Configure window background
        self.root.configure(bg=self.bg_dark)

        # Setup custom style for Notebook/Tabs
        self.setup_styles()

        # Config queue for logs
        self.log_queue = queue.Queue()

        # Build UI
        self.create_widgets()

        # Load existing config & populate UI
        self.load_and_populate_config()

        # Start checking queue for logs
        self.check_log_queue()

        # Redirect stdout and stderr
        sys.stdout = QueueWriteStream(self.log_queue)
        sys.stderr = QueueWriteStream(self.log_queue)

        print("[시스템] 프로그램이 실행되었습니다. 설정 탭을 먼저 구성해 주세요.")

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("default")

        # Custom Notebook Styles
        self.style.configure(
            "TNotebook",
            background=self.bg_dark,
            borderwidth=0
        )
        self.style.configure(
            "TNotebook.Tab",
            background=self.bg_card,
            foreground=self.text_muted,
            padding=[20, 8],
            font=("맑은 고딕", 10, "bold"),
            borderwidth=1,
            lightcolor=self.bg_dark,
            darkcolor=self.bg_dark
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", self.primary)],
            foreground=[("selected", self.text_light)]
        )

    def create_widgets(self):
        # Top Header
        header_frame = tk.Frame(self.root, bg=self.bg_dark, pady=10)
        header_frame.pack(fill="x", padx=20)

        title_lbl = tk.Label(
            header_frame,
            text="NAVER BLOG AUTO POSTER",
            font=("맑은 고딕", 16, "bold"),
            bg=self.bg_dark,
            fg=self.text_light
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            header_frame,
            text="Powered by Gemini 3.1 Flash Lite",
            font=("맑은 고딕", 9, "italic"),
            bg=self.bg_dark,
            fg=self.text_muted
        )
        subtitle_lbl.pack(side="left", padx=10, pady=5)

        # Notebook for Tabs
        self.notebook = ttk.Notebook(self.root, style="TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=20, pady=10)

        # Tab 1: Post (글쓰기)
        self.tab_post = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_post, text=" 📝 글쓰기 (Post) ")

        # Tab 2: Settings (설정)
        self.tab_settings = tk.Frame(self.notebook, bg=self.bg_dark)
        self.notebook.add(self.tab_settings, text=" ⚙️ 설정 (Settings) ")

        self.build_post_tab()
        self.build_settings_tab()

    def build_post_tab(self):
        # Main area
        post_container = tk.Frame(self.tab_post, bg=self.bg_dark)
        post_container.pack(fill="both", expand=True, pady=5)

        # Prompt input frame
        prompt_frame = tk.LabelFrame(
            post_container,
            text=" 블로그 글 생성 주제 (프롬프트 입력) ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_light,
            bd=1,
            relief="solid",
            padx=10,
            pady=10
        )
        prompt_frame.pack(fill="x", pady=5)

        self.prompt_text = tk.Text(
            prompt_frame,
            height=6,
            bg=self.bg_input,
            fg=self.text_light,
            insertbackground=self.text_light,
            font=("맑은 고딕", 10),
            bd=0,
            relief="flat",
            padx=5,
            pady=5
        )
        self.prompt_text.pack(fill="x")
        self.prompt_text.insert(
            "1.0",
            "요즘 뜨고 있는 유용한 AI 코딩 툴의 트렌드와 장점을 소개하는 글을 써줘."
        )

        # Button Frame
        btn_frame = tk.Frame(post_container, bg=self.bg_dark)
        btn_frame.pack(fill="x", pady=10)

        self.post_btn = tk.Button(
            btn_frame,
            text="🤖 AI 글 생성 및 네이버 포스팅 시작 🚀",
            font=("맑은 고딕", 11, "bold"),
            bg=self.primary,
            fg=self.text_light,
            activebackground=self.hover,
            activeforeground=self.text_light,
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=10,
            command=self.start_posting_process_thread
        )
        self.post_btn.pack(fill="x")
        self.post_btn.bind("<Enter>", lambda e: self.on_button_hover(e, self.hover))
        self.post_btn.bind("<Leave>", lambda e: self.on_button_hover(e, self.primary))

        # Log Frame
        log_frame = tk.LabelFrame(
            post_container,
            text=" 실시간 작업 로그 (Logs) ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_light,
            bd=1,
            relief="solid",
            padx=10,
            pady=10
        )
        log_frame.pack(fill="both", expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            bg=self.bg_input,
            fg="#c3e88d",  # Cool green log color
            insertbackground=self.text_light,
            font=("Consolas", 9),
            bd=0,
            relief="flat",
            state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)

    def build_settings_tab(self):
        settings_container = tk.Frame(self.tab_settings, bg=self.bg_dark)
        settings_container.pack(fill="both", expand=True, pady=10)

        # 1. API settings frame
        api_frame = tk.LabelFrame(
            settings_container,
            text=" Google Gemini API 설정 ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_light,
            bd=1,
            relief="solid",
            padx=15,
            pady=15
        )
        api_frame.pack(fill="x", pady=10)

        api_lbl = tk.Label(
            api_frame,
            text="Gemini API Key:",
            font=("맑은 고딕", 10),
            bg=self.bg_card,
            fg=self.text_muted
        )
        api_lbl.grid(row=0, column=0, sticky="w", pady=5)

        self.api_entry = tk.Entry(
            api_frame,
            width=50,
            bg=self.bg_input,
            fg=self.text_light,
            insertbackground=self.text_light,
            bd=1,
            relief="solid",
            font=("Consolas", 10),
            show="*"
        )
        self.api_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # API visibility toggle button
        self.api_visible = False
        self.api_toggle_btn = tk.Button(
            api_frame,
            text="보기",
            font=("맑은 고딕", 8),
            bg=self.accent,
            fg=self.text_light,
            activebackground=self.primary,
            activeforeground=self.text_light,
            bd=0,
            padx=8,
            pady=2,
            command=self.toggle_api_visibility
        )
        self.api_toggle_btn.grid(row=0, column=2, padx=5, pady=5)

        # 2. Naver settings frame
        naver_frame = tk.LabelFrame(
            settings_container,
            text=" 네이버 계정 설정 (DPAPI 암호화 저장) ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_light,
            bd=1,
            relief="solid",
            padx=15,
            pady=15
        )
        naver_frame.pack(fill="x", pady=10)

        id_lbl = tk.Label(
            naver_frame,
            text="네이버 ID:",
            font=("맑은 고딕", 10),
            bg=self.bg_card,
            fg=self.text_muted
        )
        id_lbl.grid(row=0, column=0, sticky="w", pady=5)

        self.id_entry = tk.Entry(
            naver_frame,
            width=50,
            bg=self.bg_input,
            fg=self.text_light,
            insertbackground=self.text_light,
            bd=1,
            relief="solid",
            font=("맑은 고딕", 10)
        )
        self.id_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        pw_lbl = tk.Label(
            naver_frame,
            text="네이버 PW:",
            font=("맑은 고딕", 10),
            bg=self.bg_card,
            fg=self.text_muted
        )
        pw_lbl.grid(row=1, column=0, sticky="w", pady=5)

        self.pw_entry = tk.Entry(
            naver_frame,
            width=50,
            bg=self.bg_input,
            fg=self.text_light,
            insertbackground=self.text_light,
            bd=1,
            relief="solid",
            font=("Consolas", 10),
            show="*"
        )
        self.pw_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # 3. Action button for settings
        self.save_settings_btn = tk.Button(
            settings_container,
            text="💾 설정 안전하게 암호화 저장",
            font=("맑은 고딕", 11, "bold"),
            bg=self.accent,
            fg=self.text_light,
            activebackground=self.hover,
            activeforeground=self.text_light,
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=12,
            command=self.save_gui_config
        )
        self.save_settings_btn.pack(fill="x", pady=20)
        self.save_settings_btn.bind("<Enter>", lambda e: self.on_button_hover(e, self.hover))
        self.save_settings_btn.bind("<Leave>", lambda e: self.on_button_hover(e, self.accent))

    def toggle_api_visibility(self):
        if self.api_visible:
            self.api_entry.configure(show="*")
            self.api_toggle_btn.configure(text="보기")
            self.api_visible = False
        else:
            self.api_entry.configure(show="")
            self.api_toggle_btn.configure(text="숨기기")
            self.api_visible = True

    def on_button_hover(self, event, color):
        if event.widget["state"] != "disabled":
            event.widget["background"] = color

    # --- Config Load/Save ---
    def load_and_populate_config(self):
        try:
            cfg = load_config()
            self.api_entry.insert(0, cfg.get("gemini_api_key", ""))
            self.id_entry.insert(0, cfg.get("naver_id", ""))
            self.pw_entry.insert(0, cfg.get("naver_pw", ""))
        except Exception as e:
            print(f"[설정 로드 오류] 저장된 설정을 불러오는 도중 오류 발생: {e}")

    def save_gui_config(self):
        cfg = {
            "gemini_api_key": self.api_entry.get().strip(),
            "naver_id":       self.id_entry.get().strip(),
            "naver_pw":       self.pw_entry.get().strip(),
        }

        if not cfg["gemini_api_key"] or not cfg["naver_id"] or not cfg["naver_pw"]:
            messagebox.showwarning("입력 오류", "모든 항목을 입력해 주셔야 저장이 가능합니다.")
            return

        try:
            save_config(cfg)
            messagebox.showinfo("저장 완료", "모든 비밀 값들이 암호화(DPAPI)되어 로컬에 성공적으로 저장되었습니다.")
            print("[시스템] 새 설정 정보가 정상적으로 암호화 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("저장 오류", f"설정 저장 도중 예외가 발생했습니다:\n{e}")
            print(f"[시스템 오류] 설정 저장 실패: {e}")

    # --- Thread Queue Checking ---
    def check_log_queue(self):
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

    # --- Posting Process ---
    def start_posting_process_thread(self):
        prompt_val = self.prompt_text.get("1.0", "end").strip()
        if not prompt_val:
            messagebox.showwarning("입력 오류", "블로그 주제 또는 프롬프트를 입력해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "Gemini API Key가 설정되지 않았습니다. 설정 탭에서 설정해 주세요.")
            return
        if not cfg.get("naver_id") or not cfg.get("naver_pw"):
            messagebox.showwarning("설정 오류", "네이버 ID/PW가 설정되지 않았습니다. 설정 탭에서 설정해 주세요.")
            return

        # Disable button & Change UI state
        self.post_btn.configure(state="disabled", text="작업 진행 중... ⏳")
        self.post_btn.configure(bg=self.accent)

        t = threading.Thread(target=self.run_posting, args=(cfg, prompt_val))
        t.daemon = True
        t.start()

    def run_posting(self, cfg, prompt_text):
        driver = None
        try:
            print("\n" + "="*60)
            print("🚀 포스팅 작업을 시작합니다.")
            print(f"[AI 생성] Gemini API (gemini-3.1-flash-lite)로 블로그 콘텐츠 생성을 요청합니다...")

            title, content = self.generate_blog_content(cfg["gemini_api_key"], prompt_text)
            
            print(f"✅ AI 콘텐츠 생성 완료!")
            print(f"👉 생성된 제목: {title}")
            print(f"👉 본문 길이: 약 {len(content)} 자")
            print("="*60)

            print("[셀레늄] 크롬 드라이버를 기동합니다...")
            uid = cfg["naver_id"]
            upw = cfg["naver_pw"]

            driver = get_driver(uid)
            ensure_logged_in(driver, uid, upw)

            print("[셀레늄] 네이버 글쓰기 모듈을 호출하여 작성합니다...")
            published_url = write_post(driver, uid, title, content)
            
            print(f"\n🎉 블로그 포스팅 최종 성공!")
            print(f"🔗 최종 포스트 주소: {published_url}")
            print("="*60)
            
            messagebox.showinfo("포스팅 완료", f"포스팅이 성공적으로 작성되었습니다!\n주소: {published_url}")

        except Exception as e:
            print(f"\n❌ 작업 진행 중 오류가 발생했습니다:\n{e}")
            traceback_output = traceback.format_exc()
            print(f"[상세 에러 트레이스백]\n{traceback_output}")
            messagebox.showerror("포스팅 실패", f"에러가 발생했습니다:\n{e}")

        finally:
            if driver:
                try:
                    driver.quit()
                    print("[셀레늄] 브라우저 세션을 종료했습니다.")
                except Exception:
                    pass
            
            # Reset button state in main thread
            self.root.after(0, self.reset_post_button)

    def reset_post_button(self):
        self.post_btn.configure(state="normal", text="🤖 AI 글 생성 및 네이버 포스팅 시작 🚀")
        self.post_btn.configure(bg=self.primary)

    def generate_blog_content(self, api_key, prompt_text):
        client = genai.Client(api_key=api_key)
        system_instruction = """
당신은 네이버 블로그 포스팅을 전문으로 하는 지식이 풍부하고 유려한 에디터입니다.
사용자가 제공하는 주제/프롬프트에 맞추어 전문적이면서도 친근한 어투(이웃에게 말하듯 편안한 스타일, ~습니다, ~해요체)로 한국어 글을 작성하세요.
문단 구분을 확실하게 하여 가독성을 높여 주시기 바랍니다.

반드시 아래 JSON 스키마 형식으로만 응답해야 하며, 어떠한 코드 블록(예: ```json 등)이나 마크다운 래핑 없이 순수한 JSON 내용만 제공해야 합니다.

응답 형식 JSON:
{
  "title": "블로그 포스트의 시선을 사로잡는 어울리는 제목",
  "content": "풍부하고 상세하게 서술된 본문 내용 (단락 구분을 위해 줄바꿈 \\n을 활용하세요)"
}
"""
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.7
            )
        )
        raw = (response.text or "").strip()
        
        # Strip potential markdown formatting wraps
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw).strip()

        # Parse JSON safely with a robust fallback
        try:
            data = json.loads(raw)
            title = data.get("title", f"블로그 포스트: {prompt_text[:15]}...")
            content = data.get("content", raw)
            return title, content
        except Exception as json_err:
            print(f"[경고] JSON 응답 파싱 실패로 텍스트 분할 폴백을 실행합니다: {json_err}")
            # Fallback parsing strategy
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if lines:
                title = lines[0].replace("#", "").replace('"', '').replace("'", "").strip()
                content = "\n\n".join(lines[1:])
            else:
                title = f"블로그 포스트: {prompt_text[:15]}..."
                content = raw
            return title, content

if __name__ == "__main__":
    root = tk.Tk()
    app = NaverPosterGUI(root)
    root.mainloop()
