# pyright: reportMissingImports=false
"""
news_analyzer.py — 뉴스 기사 분석 UI 섹션
구글 뉴스 RSS 기사 선택 → Gemini 단계별 분석 → Desktop/lists/ 저장
"""
import re
import json
import threading
import traceback
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import tkinter as tk
from tkinter import ttk, messagebox
from google import genai
from google.genai import types

try:
    from standalone_poster import load_config
except ImportError:
    pass  # 오류는 gui_app.py 에서 처리

KST = timezone(timedelta(hours=9))


class NewsAnalyzerSection:
    """
    뉴스 기사 분석 섹션.
    build(container) 를 호출하면 container 안에 UI 전체를 구성한다.
    """

    def __init__(self, root: tk.Tk, theme: dict):
        self.root       = root
        self.bg_card      = theme["bg_card"]
        self.bg_input     = theme["bg_input"]
        self.text_light   = theme["text_light"]
        self.text_dark    = theme.get("text_dark",    "#1A1A1A")
        self.text_muted   = theme["text_muted"]
        self.accent       = theme["accent"]
        self.hover        = theme["hover"]
        self.hover_dark   = theme.get("hover_dark",   "#E6B800")
        self.btn_rss      = theme["btn_rss"]
        self.tertiary     = theme.get("tertiary",     "#0055FF")
        self.tertiary_hov = theme.get("tertiary_hov", "#003DD6")
        self.primary      = theme.get("primary",      "#1A1A1A")
        self.border_color = theme.get("border_color", "#1A1A1A")
        self.article_vars: list = []

    # ──────────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────────
    def build(self, container: tk.Frame) -> None:
        rss_frame = tk.LabelFrame(
            container,
            text="  뉴스 기사 분석  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_dark,
            bd=3,
            relief="solid",
            padx=10,
            pady=10,
        )
        rss_frame.pack(fill="x", pady=4)

        # ─ URL 입력 ─
        url_row = tk.Frame(rss_frame, bg=self.bg_card)
        url_row.pack(fill="x", pady=(0, 6))

        tk.Label(
            url_row,
            text="RSS URL:",
            font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card,
            fg=self.text_dark,
        ).pack(side="left", padx=(0, 6))

        self.rss_url_entry = tk.Entry(
            url_row,
            bg=self.bg_input,
            fg=self.text_dark,
            insertbackground=self.text_dark,
            bd=2,
            relief="solid",
            font=("Consolas", 9),
        )
        self.rss_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.rss_url_entry.insert(0, "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko")

        self.load_btn = tk.Button(
            url_row,
            text="📥 불러오기",
            font=("맑은 고딕", 9, "bold"),
            bg=self.primary,
            fg=self.text_light,
            activebackground=self.accent, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=self.load_rss_articles,
        )
        self.load_btn.pack(side="left")
        self._bind_hover(self.load_btn, self.primary, self.accent)

        # ─ 상태 레이블 ─
        self.article_count_lbl = tk.Label(
            rss_frame,
            text="RSS URL을 입력하고 [불러오기] 버튼을 눌러 기사를 가져오세요.",
            font=("맑은 고딕", 8),
            bg=self.bg_card,
            fg=self.text_muted,
            anchor="w",
        )
        self.article_count_lbl.pack(fill="x", pady=(0, 4))

        # ─ 스크롤 가능한 체크박스 목록 ─
        list_outer = tk.Frame(rss_frame, bg=self.border_color, bd=2, relief="solid")
        list_outer.pack(fill="x", pady=(0, 6))

        self.articles_canvas = tk.Canvas(
            list_outer, bg=self.bg_input, height=155, bd=0, highlightthickness=0,
        )
        art_scroll = ttk.Scrollbar(
            list_outer, orient="vertical", command=self.articles_canvas.yview,
        )
        self.articles_canvas.configure(yscrollcommand=art_scroll.set)
        art_scroll.pack(side="right", fill="y")
        self.articles_canvas.pack(side="left", fill="both", expand=True)

        self.articles_inner = tk.Frame(self.articles_canvas, bg=self.bg_input)
        _win = self.articles_canvas.create_window((0, 0), window=self.articles_inner, anchor="nw")

        self.articles_inner.bind(
            "<Configure>",
            lambda e: self.articles_canvas.configure(
                scrollregion=self.articles_canvas.bbox("all")
            ),
        )
        self.articles_canvas.bind(
            "<Configure>",
            lambda e: self.articles_canvas.itemconfig(_win, width=e.width),
        )
        self.articles_canvas.bind(
            "<Enter>",
            lambda e: self.articles_canvas.bind_all("<MouseWheel>", self._scroll_articles),
        )
        self.articles_canvas.bind(
            "<Leave>",
            lambda e: self.articles_canvas.unbind_all("<MouseWheel>"),
        )

        placeholder_lbl = tk.Label(
            self.articles_inner,
            text="(기사 목록이 여기에 표시됩니다)",
            font=("맑은 고딕", 9),
            bg=self.bg_input,
            fg=self.text_muted,
        )
        placeholder_lbl.pack(pady=20)

        # ─ 선택 제어 + 날짜 필터 ─
        sel_row = tk.Frame(rss_frame, bg=self.bg_card)
        sel_row.pack(fill="x", pady=(0, 6))

        # 전체 선택 / 해제
        for label, cmd in [("전체 선택", self.select_all_articles), ("전체 해제", self.deselect_all_articles)]:
            btn = tk.Button(
                sel_row,
                text=label,
                font=("맑은 고딕", 8, "bold"),
                bg=self.bg_card,
                fg=self.text_dark,
                activebackground=self.accent, activeforeground=self.text_dark,
                bd=2, relief="solid", cursor="hand2",
                padx=10, pady=2,
                command=cmd,
            )
            btn.pack(side="left", padx=(0, 6))
            self._bind_hover(btn, self.bg_card, self.accent)

        # 구분선
        tk.Frame(sel_row, bg=self.border_color, width=2).pack(
            side="left", fill="y", padx=(4, 10), pady=2
        )

        # 날짜 필터 버튼 (Yellow)
        for label, period in [("오늘", "today"), ("이번주", "week"), ("이번달", "month")]:
            btn = tk.Button(
                sel_row,
                text=label,
                font=("맑은 고딕", 8, "bold"),
                bg=self.accent,
                fg=self.text_dark,
                activebackground=self.hover_dark, activeforeground=self.text_dark,
                bd=0, relief="flat", cursor="hand2",
                padx=10, pady=2,
                command=lambda p=period: self._filter_by_date(p),
            )
            btn.pack(side="left", padx=(0, 4))
            self._bind_hover(btn, self.accent, self.hover_dark)

        # ─ 분석 & 저장 버튼 (Blue) ─
        self.analyze_btn = tk.Button(
            rss_frame,
            text="📊  선택된 기사 분석하여 파일 저장",
            font=("맑은 고딕", 11, "bold"),
            bg=self.btn_rss,
            fg=self.text_light,
            activebackground=self.tertiary_hov, activeforeground=self.text_light,
            bd=0, relief="flat", cursor="hand2",
            padx=20, pady=12,
            command=self.start_analysis_thread,
        )
        self.analyze_btn.pack(fill="x", pady=(4, 0))
        self._bind_hover(self.analyze_btn, self.btn_rss, self.tertiary_hov)

    # ──────────────────────────────────────────────
    # UI 헬퍼
    # ──────────────────────────────────────────────
    def _bind_hover(self, btn: tk.Button, normal_bg: str, hover_bg: str = "") -> None:
        hov = hover_bg or self.accent
        btn.bind("<Enter>", lambda e: self._on_hover(e, hov))
        btn.bind("<Leave>", lambda e: self._on_hover(e, normal_bg))

    def _on_hover(self, event, color: str) -> None:
        if event.widget["state"] != "disabled":
            event.widget["background"] = color

    def _scroll_articles(self, event) -> None:
        self.articles_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _reset_btn(self, btn: tk.Button, text: str, bg: str) -> None:
        btn.configure(state="normal", text=text, bg=bg)

    # ──────────────────────────────────────────────
    # RSS 로드 & 파싱
    # ──────────────────────────────────────────────
    def load_rss_articles(self) -> None:
        url = self.rss_url_entry.get().strip()
        if not url:
            messagebox.showwarning("입력 오류", "RSS URL을 입력해 주세요.")
            return

        self.load_btn.configure(state="disabled", text="불러오는 중... ⏳")
        self.article_count_lbl.configure(text="기사를 불러오는 중입니다...")

        def fetch():
            try:
                articles = self._parse_rss_feed(url)
                self.root.after(0, lambda: self._populate_article_list(articles))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._on_rss_load_error(msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _parse_rss_feed(self, url: str) -> list:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_bytes = resp.read()

        root_el = ET.fromstring(raw_bytes)
        ns = (root_el.tag.split("}")[0] + "}") if root_el.tag.startswith("{") else ""
        channel = root_el.find(f"{ns}channel") or root_el

        def _text(item, tag: str) -> str:
            el = item.find(f"{ns}{tag}")
            return (el.text or "").strip() if el is not None else ""

        articles = []
        for item in channel.findall(f"{ns}item"):
            title    = _text(item, "title") or "(제목 없음)"
            raw_desc = _text(item, "description")
            desc     = re.sub(r"<[^>]+>", "", raw_desc).strip() if raw_desc else ""
            pub_date = _text(item, "pubDate")

            articles.append({
                "title":        title,
                "description":  desc[:500],
                "link":         _text(item, "link"),
                "pubDate":      pub_date,
                "display_date": self._parse_kst(pub_date),
            })

        return articles

    def _parse_kst(self, pub_date_str: str) -> str:
        if not pub_date_str:
            return ""
        try:
            dt = parsedate_to_datetime(pub_date_str)
            return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return pub_date_str[:16]

    def _populate_article_list(self, articles: list) -> None:
        for widget in self.articles_inner.winfo_children():
            widget.destroy()
        self.article_vars.clear()

        if not articles:
            tk.Label(
                self.articles_inner,
                text="(가져온 기사가 없습니다)",
                font=("맑은 고딕", 9),
                bg=self.bg_input,
                fg=self.text_muted,
            ).pack(pady=20)
        else:
            for i, article in enumerate(articles):
                var    = tk.BooleanVar(value=False)
                row_bg = "#FFFFFF" if i % 2 == 0 else "#F5F0E8"
                cb = tk.Checkbutton(
                    self.articles_inner,
                    text=f"[{article['display_date']}]  {article['title']}",
                    variable=var,
                    anchor="w",
                    font=("맑은 고딕", 8),
                    bg=row_bg, fg=self.text_dark,
                    selectcolor=self.accent,
                    activebackground=self.accent,
                    activeforeground=self.text_dark,
                    bd=0, relief="flat",
                    padx=8, pady=3,
                    wraplength=720, justify="left",
                )
                cb.pack(fill="x", anchor="w")
                self.article_vars.append((var, article))

        self.article_count_lbl.configure(
            text=f"총 {len(articles)}개 기사 로드 완료 — 분석할 기사를 체크박스로 선택하세요."
        )
        self.load_btn.configure(state="normal", text="📥 불러오기")

    def _on_rss_load_error(self, msg: str) -> None:
        self.article_count_lbl.configure(text=f"오류: {msg[:100]}")
        self.load_btn.configure(state="normal", text="📥 불러오기")
        messagebox.showerror("RSS 불러오기 오류", f"RSS 피드 로드 중 오류가 발생했습니다:\n\n{msg}")

    def _set_all_articles(self, value: bool) -> None:
        for var, _ in self.article_vars:
            var.set(value)

    def select_all_articles(self) -> None:
        self._set_all_articles(True)

    def deselect_all_articles(self) -> None:
        self._set_all_articles(False)

    def _filter_by_date(self, period: str) -> None:
        """오늘/이번주/이번달 기사만 체크, 나머지는 해제."""
        now   = datetime.now(KST)
        today = now.date()

        if period == "week":
            # 이번주 월요일 ~ 오늘
            week_start = today - timedelta(days=today.weekday())
        elif period == "month":
            month_start = today.replace(day=1)

        matched = 0
        for var, article in self.article_vars:
            date_str = article.get("display_date", "")[:10]   # 'YYYY-MM-DD'
            try:
                art_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if period == "today":
                    ok = (art_date == today)
                elif period == "week":
                    ok = (week_start <= art_date <= today)
                else:   # month
                    ok = (month_start <= art_date <= today)
            except ValueError:
                ok = False
            var.set(ok)
            if ok:
                matched += 1

        label_map = {"today": "오늘", "week": "이번주", "month": "이번달"}
        self.article_count_lbl.configure(
            text=f"[{label_map[period]} 필터] {matched}개 기사 선택됨"
        )

    # ──────────────────────────────────────────────
    # 분석 & 저장
    # ──────────────────────────────────────────────
    def start_analysis_thread(self) -> None:
        selected = [art for var, art in self.article_vars if var.get()]
        if not selected:
            messagebox.showwarning("선택 오류", "분석할 기사를 하나 이상 체크박스로 선택해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류", "Gemini API Key가 설정되지 않았습니다.\n설정 탭에서 입력해 주세요.")
            return

        self.analyze_btn.configure(state="disabled", text="분석 중... ⏳", bg="#4A4A4A")
        threading.Thread(target=self._run_analysis, args=(cfg, selected), daemon=True).start()

    def _run_analysis(self, cfg: dict, articles: list) -> None:
        try:
            print("\n" + "=" * 60)
            print(f"📰 선택된 기사 {len(articles)}개 분석을 시작합니다...")

            now          = datetime.now(KST)
            now_display  = now.strftime("%Y-%m-%d %H:%M")   # 문서 내용용
            now_filename = now.strftime("%Y-%m-%d %H-%M")   # 파일명용 (07-03 형식)
            art_text     = self._build_articles_text(articles)
            model_id     = cfg.get("gemini_model", "gemini-3.1-flash-lite")
            client       = genai.Client(api_key=cfg["gemini_api_key"])

            # 1단계: 제목 · 소제목 · 태그
            print(f"[1단계] 제목 · 소제목 목록 · 태그 생성 중... (모델: {model_id})")
            outline    = self._gen_outline(client, art_text, len(articles), model_id)
            title      = outline.get("title", "뉴스 분석 포스팅")
            sub_titles = outline.get("subheadings", [])
            tags       = outline.get("tags", [])
            print(f"✅ 제목: {title} ({now_display})")
            print(f"   소제목 {len(sub_titles)}개 / 태그 {len(tags)}개")

            # 파일 경로
            lists_dir = Path.home() / "Desktop" / "lists"
            lists_dir.mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
            safe_name  = re.sub(r"\s+", " ", f"{now_filename} {safe_title}")[:80]
            file_path  = lists_dir / f"{safe_name}.txt"

            total = len(sub_titles)
            with open(file_path, "w", encoding="utf-8") as f:

                # 제목 + 날짜/시간 기록
                f.write(f"제목: {title}\n")
                f.write(f"작성 일시: {now_display} (KST)\n\n")
                f.write("=" * 60 + "\n")
                f.flush()

                # 2단계: 소제목 전체 일괄 분석 (API 1회 요청)
                print(f"[2단계] {total}개 소제목 일괄 분석 중... (API 1회 요청)")
                self.root.after(
                    0,
                    lambda n=total: self.analyze_btn.configure(
                        text=f"일괄 분석 중... ({n}개) ⏳"
                    ),
                )
                all_analyses = self._gen_all_analyses(client, art_text, sub_titles, model_id)

                for sub_title, analysis in all_analyses:
                    f.write(f"\n{sub_title}\n\n{analysis}\n\n")
                    f.flush()
                print(f"   ✅ {total}개 분석 완료 (총 API 호출: 2회)")

                # 3단계: 출처 기사
                f.write("\n" + "=" * 60 + "\n")
                f.write("출처 기사:\n")
                for art in articles:
                    f.write(f"  - {art['title']} ({art.get('display_date', '')})\n")
                f.flush()
                print("[3단계] 출처 기사 기록 완료")

                # 4단계: 태그 (맨 마지막)
                f.write("\n" + "=" * 60 + "\n")
                f.write("태그: " + "  ".join(f"#{t}" for t in tags) + "\n")

            print("[4단계] 태그 기록 완료 → 파일 닫힘")
            fp_str = str(file_path)
            print(f"💾 저장 완료: {fp_str}\n" + "=" * 60)

            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "분석 & 저장 완료",
                    f"분석 포스팅이 저장되었습니다!\n\n📁 저장 위치:\n{fp_str}",
                ),
            )

        except Exception as e:
            err = str(e)
            print(f"\n❌ 분석 중 오류:\n{err}\n{traceback.format_exc()}")
            self.root.after(
                0,
                lambda: messagebox.showerror("분석 실패", f"분석 도중 오류가 발생했습니다:\n\n{err}"),
            )

        finally:
            self.root.after(
                0,
                lambda: self._reset_btn(
                    self.analyze_btn, "📊 선택된 기사 분석하여 파일 저장", self.btn_rss
                ),
            )

    # ──────────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────────
    def _build_articles_text(self, articles: list) -> str:
        parts = []
        for i, art in enumerate(articles, 1):
            parts.append(f"\n[기사 {i}]\n제목: {art['title']}\n")
            if art.get("description"):
                parts.append(f"요약: {art['description'][:400]}\n")
            if art.get("pubDate"):
                parts.append(f"날짜: {art['pubDate'][:30]}\n")
        return "".join(parts)

    def _clean_json(self, raw: str) -> str:
        return re.sub(
            r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.IGNORECASE
        ).strip()

    # ──────────────────────────────────────────────
    # Gemini 호출
    # ──────────────────────────────────────────────
    def _gen_outline(self, client, art_text: str, n_articles: int, model_id: str = "gemini-3.1-flash-lite") -> dict:
        sys_inst = f"""
당신은 뉴스 기사 분석 전문 에디터입니다.
제공된 기사들을 바탕으로 아래 JSON 형식으로만 응답하세요.
코드 블록 없이 순수 JSON만 출력하세요.

{{
  "title": "분석 포스트 제목 (흥미롭고 SEO 최적화)",
  "subheadings": ["소제목1", "소제목2", ...],
  "tags": ["태그1", ..., "태그12이상"]
}}

규칙:
- subheadings: 기사 {n_articles}개에 맞게 정확히 {n_articles}개 문자열 (분석 내용 없이 소제목만)
- tags: 핵심 키워드 12개 이상, 한국어 단어
- title: 기사 주제 반영, SEO 최적화
"""
        resp = client.models.generate_content(
            model=model_id,
            contents=f"다음 기사들의 분석 포스팅 목차를 작성해 주세요:\n{art_text}",
            config=types.GenerateContentConfig(
                system_instruction=sys_inst,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        try:
            data = json.loads(self._clean_json(resp.text or ""))
            subs = data.get("subheadings", [])
            if subs and isinstance(subs[0], dict):
                subs = [s.get("title", "") for s in subs]
            data["subheadings"] = subs
            return data
        except Exception:
            return {
                "title": "뉴스 분석 포스팅",
                "subheadings": [f"기사 {i} 분석" for i in range(1, n_articles + 1)],
                "tags": [],
            }

    def _gen_all_analyses(
        self,
        client,
        art_text: str,
        sub_titles: list,
        model_id: str = "gemini-3.1-flash-lite",
    ) -> list:
        """
        모든 소제목 분석을 1번의 API 호출로 처리.
        Returns: list of (title, analysis) tuples
        """
        n = len(sub_titles)
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(sub_titles))

        sys_inst = f"""
당신은 뉴스 기사 분석 전문 에디터입니다.
제공된 기사들과 소제목 목록을 바탕으로 각 소제목에 대한 심층 분석을 한 번에 작성하세요.
코드 블록 없이 순수 JSON만 출력하세요.

{{
  "analyses": [
    {{"title": "소제목", "analysis": "분석 내용"}},
    ...
  ]
}}

규칙:
- analyses 배열은 반드시 {n}개 (입력 소제목 순서 동일)
- 각 title은 입력된 소제목 그대로 사용
- 각 analysis: 수치(%, 금액, 연도, 순위) 반드시 포함, 700자 내외
- 객관적 사실 기반, 한국어
"""
        user_message = (
            f"기사 목록:\n{art_text}\n\n"
            f"소제목 목록 ({n}개):\n{numbered}\n\n"
            "위 기사를 바탕으로 각 소제목에 대한 분석을 작성해 주세요."
        )

        resp = client.models.generate_content(
            model=model_id,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=sys_inst,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )

        try:
            data = json.loads(self._clean_json(resp.text or ""))
            raw_list = data.get("analyses", [])
        except Exception as e:
            print(f"[경고] 일괄 분석 JSON 파싱 실패: {e}")
            raw_list = []

        # 결과를 소제목 순서에 맞게 정렬 (누락 분 보완)
        result = []
        for i, sub_title in enumerate(sub_titles):
            if i < len(raw_list):
                item = raw_list[i]
                analysis = item.get("analysis", "(분석 내용 없음)")
            else:
                analysis = "(분석 누락)"
            result.append((sub_title, analysis))

        return result
