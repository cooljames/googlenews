# pyright: reportMissingImports=false
"""
industry_section.py — 네이버 업종별 종목 탐색 섹션
업종 드롭다운 → 시가총액순 종목 테이블 → 선택 종목을 StockReportSection에 전달
"""
import json
import threading
import urllib.request

import tkinter as tk
from tkinter import ttk, messagebox

NAVER_INDUSTRY_LIST   = "https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100"
NAVER_INDUSTRY_STOCKS = (
    "https://m.stock.naver.com/api/stocks/industry/{no}"
    "?page=1&pageSize=100&sortType=marketValue&sortOrder=desc"
)


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _fmt_mktcap(raw: int) -> str:
    if raw >= 1_000_000_000_000:
        return f"{raw / 1_000_000_000_000:.1f}조"
    if raw >= 100_000_000:
        return f"{raw / 100_000_000:.0f}억"
    return f"{raw:,}"


class IndustrySectorSection:
    """업종 탐색 섹션. build(container) 로 UI 구성."""

    def __init__(self, root: tk.Tk, theme: dict, report_section):
        self.root           = root
        self.report_section = report_section   # StockReportSection 참조
        self.bg_card        = theme["bg_card"]
        self.bg_input       = theme["bg_input"]
        self.text_light     = theme["text_light"]
        self.text_dark      = theme.get("text_dark", "#1A1A1A")
        self.text_muted     = theme["text_muted"]
        self.accent         = theme["accent"]
        self.btn_rss        = theme["btn_rss"]
        self.tertiary_hov   = theme.get("tertiary_hov", "#003DD6")
        self.primary        = theme.get("primary", "#1A1A1A")
        self._groups: list  = []
        self._stocks: list  = []

    # ──────────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────────
    def build(self, container: tk.Frame) -> None:
        frame = tk.LabelFrame(
            container,
            text="  📊 업종별 종목 탐색 (한국)  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid", padx=10, pady=10,
        )
        frame.pack(fill="x", pady=4)

        # ── 1행: 업종 드롭다운 + 새로고침 + 통계 ──
        top_row = tk.Frame(frame, bg=self.bg_card)
        top_row.pack(fill="x", pady=(0, 6))

        tk.Label(top_row, text="업종:",
                 font=("맑은 고딕", 9, "bold"),
                 bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(0, 4))

        self.industry_var = tk.StringVar()
        self.industry_cb  = ttk.Combobox(
            top_row, textvariable=self.industry_var,
            state="readonly", width=22, font=("맑은 고딕", 9),
        )
        self.industry_cb.pack(side="left", padx=(0, 8))
        self.industry_cb.bind("<<ComboboxSelected>>", self._on_industry_select)

        self.refresh_btn = tk.Button(
            top_row, text="🔄 업종 목록",
            font=("맑은 고딕", 9), bg=self.primary, fg=self.text_light,
            bd=0, relief="flat", cursor="hand2", padx=8, pady=4,
            command=self._load_industries_thread,
        )
        self.refresh_btn.pack(side="left", padx=(0, 12))

        self.stats_lbl = tk.Label(
            top_row, text="업종을 불러오는 중...",
            font=("맑은 고딕", 8), bg=self.bg_card, fg=self.text_muted,
        )
        self.stats_lbl.pack(side="left")

        # ── 2행: 종목 Treeview ──
        tree_frame = tk.Frame(frame, bg=self.bg_card)
        tree_frame.pack(fill="x", pady=(0, 6))

        cols = ("순위", "종목명", "시가총액", "종가", "등락률", "거래소")
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            selectmode="extended", height=8,
        )
        col_cfg = [
            ("순위",   40, "center"),
            ("종목명", 130, "w"),
            ("시가총액", 90, "e"),
            ("종가",    90, "e"),
            ("등락률",  75, "e"),
            ("거래소",  55, "center"),
        ]
        for col, width, anchor in col_cfg:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("rise", foreground="#E63B2E")
        self.tree.tag_configure("fall", foreground="#0055FF")
        self.tree.tag_configure("odd",  background="#F7F3EC")

        # ── 3행: 선택·실행 버튼 ──
        btn_row = tk.Frame(frame, bg=self.bg_card)
        btn_row.pack(fill="x")

        for text, cmd, padx in [
            ("상위 5 선택",  self._select_top5,  (0, 6)),
            ("전체 선택",   self._select_all,    (0, 6)),
            ("선택 해제",   self._deselect_all,  (0, 16)),
        ]:
            tk.Button(
                btn_row, text=text,
                font=("맑은 고딕", 9), bg=self.bg_input, fg=self.text_dark,
                bd=1, relief="solid", cursor="hand2", padx=8, pady=5,
                command=cmd,
            ).pack(side="left", padx=padx)

        self.analyze_btn = tk.Button(
            btn_row,
            text="📊  선택 종목 리포트 생성",
            font=("맑은 고딕", 10, "bold"),
            bg=self.btn_rss, fg=self.text_light,
            activebackground=self.tertiary_hov, activeforeground=self.text_light,
            bd=0, relief="flat", cursor="hand2", padx=16, pady=6,
            command=self._send_to_report,
        )
        self.analyze_btn.pack(side="left")

        # 초기 업종 목록 로드
        self._load_industries_thread()

    # ──────────────────────────────────────────────
    # 업종 목록 로드
    # ──────────────────────────────────────────────
    def _load_industries_thread(self):
        self.refresh_btn.configure(state="disabled", text="로딩 중...")
        threading.Thread(target=self._load_industries, daemon=True).start()

    def _load_industries(self):
        try:
            data     = _fetch_json(NAVER_INDUSTRY_LIST)
            groups   = data.get("groups", [])
            # 업종명 가나다순 정렬
            self._groups = sorted(groups, key=lambda g: g["name"])
            names = [
                f"{g['name']}  ({g['totalCount']}종목)"
                for g in self._groups
            ]
            self.root.after(0, lambda n=names: self._update_cb(n))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                "업종 목록 오류", f"업종 목록 조회 실패:\n{e}"))
        finally:
            self.root.after(0, lambda: self.refresh_btn.configure(
                state="normal", text="🔄 업종 목록"))

    def _update_cb(self, names: list):
        self.industry_cb["values"] = names
        if names:
            self.industry_cb.current(0)
            self._on_industry_select(None)

    # ──────────────────────────────────────────────
    # 업종 선택 시 종목 로드
    # ──────────────────────────────────────────────
    def _on_industry_select(self, _event):
        idx = self.industry_cb.current()
        if not (0 <= idx < len(self._groups)):
            return
        group = self._groups[idx]
        self.stats_lbl.configure(
            text=f"{group['name']} 종목 로딩 중...", fg=self.text_muted)
        threading.Thread(
            target=self._load_sector_stocks, args=(group,), daemon=True
        ).start()

    def _load_sector_stocks(self, group: dict):
        try:
            data = _fetch_json(NAVER_INDUSTRY_STOCKS.format(no=group["no"]))
            stocks = data.get("stocks", [])
            # 시가총액 Raw 내림차순 (API가 정렬하지만 혹시 모를 보정)
            self._stocks = sorted(
                stocks,
                key=lambda s: int(s.get("marketValueRaw", 0)),
                reverse=True,
            )
            self.root.after(0, lambda g=group: self._populate_tree(g))
        except Exception as e:
            self.root.after(0, lambda: self.stats_lbl.configure(
                text=f"오류: {e}", fg="#E63B2E"))

    def _populate_tree(self, group: dict):
        for row in self.tree.get_children():
            self.tree.delete(row)

        cr    = float(group.get("changeRate", 0))
        sign  = "▲" if cr >= 0 else "▼"
        color = "#E63B2E" if cr >= 0 else "#0055FF"
        self.stats_lbl.configure(
            fg=color,
            text=(
                f"{sign} {abs(cr):.2f}%  |  "
                f"상승 {group['riseCount']}  하락 {group['fallCount']}  "
                f"보합 {group['steadyCount']}  (총 {group['totalCount']}종목)"
            ),
        )

        for i, s in enumerate(self._stocks):
            mkt_raw = int(s.get("marketValueRaw", 0))
            ratio   = float(s.get("fluctuationsRatio", 0))
            ex      = s.get("stockExchangeType", {})
            ex_code = ex.get("code", "KS") if isinstance(ex, dict) else str(ex)

            tags = []
            if ratio > 0:   tags.append("rise")
            elif ratio < 0: tags.append("fall")
            if i % 2 == 1:  tags.append("odd")

            arrow = "▲" if ratio >= 0 else "▼"
            self.tree.insert(
                "", "end", iid=str(i),
                values=(
                    i + 1,
                    s.get("stockName", ""),
                    _fmt_mktcap(mkt_raw),
                    s.get("closePrice", ""),
                    f"{arrow} {abs(ratio):.2f}%",
                    ex_code,
                ),
                tags=tuple(tags),
            )

    # ──────────────────────────────────────────────
    # 선택 헬퍼
    # ──────────────────────────────────────────────
    def _select_top5(self):
        children = self.tree.get_children()
        self.tree.selection_set(children[:5])

    def _select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _deselect_all(self):
        self.tree.selection_remove(self.tree.get_children())

    # ──────────────────────────────────────────────
    # 선택 종목 → StockReportSection 연동
    # ──────────────────────────────────────────────
    def _send_to_report(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("선택 없음", "리포트에 포함할 종목을 선택해 주세요.\n(Ctrl+클릭으로 복수 선택 가능)")
            return

        tickers = []
        for iid in selected:
            s       = self._stocks[int(iid)]
            code    = s.get("itemCode", "")
            ex      = s.get("stockExchangeType", {})
            ex_code = ex.get("code", "KS") if isinstance(ex, dict) else str(ex)
            tickers.append(f"{code}.{ex_code}")

        # StockReportSection 티커 입력란 자동 채우기
        self.report_section.ticker_entry.delete(0, "end")
        self.report_section.ticker_entry.insert(0, ", ".join(tickers))

        # 시장을 한국으로 자동 설정
        self.report_section.market_var.set("🇰🇷 한국")

        # 리포트 즉시 생성
        self.report_section.start_report_thread()
