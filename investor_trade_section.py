# pyright: reportMissingImports=false
"""
investor_trade_section.py — 기관별·기간별 순매수/순매도 상위 종목 탐색 섹션
KRX(한국거래소) 공개 데이터 포털을 활용해 투자자별 매매 동향 분석
"""
import json
import threading
import urllib.request
import urllib.parse
from datetime import date, timedelta

import tkinter as tk
from tkinter import ttk, messagebox


# ─── KRX 데이터 포털 상수 ────────────────────────────────────────────
KRX_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":      "http://data.krx.co.kr/",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept":       "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# 투자자 유형 코드 (KRX 기준)
INVESTOR_TYPES: dict[str, str] = {
    "외국인":         "2000",
    "기관계":         "3000",
    "금융투자(증권)":  "3100",
    "보험":           "3200",
    "투신(펀드)":     "3300",
    "사모펀드":       "3400",
    "은행":           "3500",
    "연기금":         "3700",
    "개인":           "1000",
}

# 기간 선택 → 캘린더 일수
PERIODS: dict[str, int] = {
    "당일":  0,
    "1주":   7,
    "1개월": 30,
    "3개월": 90,
    "6개월": 180,
}

# 시장 ID
MARKETS: dict[str, str] = {
    "KOSPI":         "STK",
    "KOSDAQ":        "KSQ",
    "KOSPI+KOSDAQ":  "ALL",
}

TRADE_DIRS = ["순매수 상위", "순매도 상위"]

# Treeview 컬럼 설정
COLS = [
    ("순위",          45,  "center", None),
    ("종목명",       130,  "w",      None),
    ("코드",          58,  "center", None),
    ("순매수량(주)",  105,  "e",      "NETBUY_TRDVOL"),
    ("순매수금액",    105,  "e",      "NETBUY_TRDVAL"),
    ("종가",           80,  "e",      None),
    ("등락률",         68,  "e",      "FLUC_RT"),
    ("거래대금",      105,  "e",      "ACC_TRDVAL"),
]


# ─── 유틸 함수 ───────────────────────────────────────────────────────
def _last_weekday(d: date | None = None) -> str:
    d = d or date.today()
    while d.weekday() >= 5:          # 토=5, 일=6
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _date_before(calendar_days: int) -> str:
    return _last_weekday(date.today() - timedelta(days=calendar_days))


def _as_int(val) -> int:
    try:
        return int(str(val).replace(",", "").replace("+", "").strip() or "0")
    except Exception:
        return 0


def _as_float(val) -> float:
    try:
        return float(str(val).replace(",", "").replace("+", "").strip() or "0")
    except Exception:
        return 0.0


def _fmt_amount(val_mil: int) -> str:
    """백만원 단위 정수 → 조/억/백만 문자열 (부호 포함)."""
    sign = "+" if val_mil >= 0 else "-"
    v = abs(val_mil)
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.2f}조"
    if v >= 10_000:
        return f"{sign}{v / 10_000:.0f}억"
    if v >= 100:
        return f"{sign}{v:,}백만"
    return f"{sign}{v}백만"


def _krx_post(params: dict) -> list:
    data = urllib.parse.urlencode(params).encode("utf-8")
    req  = urllib.request.Request(KRX_URL, data=data, headers=KRX_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = json.loads(r.read().decode("utf-8"))
    return raw.get("OutBlock_1", [])


def _fetch_ranking(mkt_id: str, investor_code: str, period_days: int) -> list:
    """KRX 투자자별 순매수 상위 50개 종목 조회."""
    today = _last_weekday()
    common = {
        "strtRcpsOrd": "1",
        "endRcpsOrd":  "50",
        "share":       "1",
        "money":       "3",          # 백만원 단위
        "csvxls_isNo": "false",
    }
    if period_days == 0:
        params = {
            "bld":       "dbms/MDC/STAT/standard/MDCSTAT02301",
            "trdDd":     today,
            "mktId":     mkt_id,
            "invstTpCd": investor_code,
            **common,
        }
    else:
        params = {
            "bld":       "dbms/MDC/STAT/standard/MDCSTAT02302",
            "strtDd":    _date_before(period_days),
            "endDd":     today,
            "mktId":     mkt_id,
            "invstTpCd": investor_code,
            **common,
        }
    rows = _krx_post(params)
    suffix = "KS" if mkt_id == "STK" else "KQ"
    for r in rows:
        r["_sfx"] = suffix
    return rows


# ─── 섹션 클래스 ─────────────────────────────────────────────────────
class InvestorTradeSection:
    """기관별 매매 동향 탐색 섹션. build(container) 로 UI 구성."""

    def __init__(self, root: tk.Tk, theme: dict, report_section):
        self.root           = root
        self.report_section = report_section
        self.bg_card        = theme["bg_card"]
        self.bg_input       = theme["bg_input"]
        self.text_light     = theme["text_light"]
        self.text_dark      = theme.get("text_dark", "#1A1A1A")
        self.text_muted     = theme["text_muted"]
        self.btn_rss        = theme["btn_rss"]
        self.tertiary_hov   = theme.get("tertiary_hov", "#003DD6")
        self.primary        = theme.get("primary", "#1A1A1A")
        self._stocks: list  = []
        self._sort_col: str = "NETBUY_TRDVAL"
        self._sort_rev: bool = True

    # ─── UI 구성 ─────────────────────────────────────────────────────
    def build(self, container: tk.Frame) -> None:
        outer = tk.LabelFrame(
            container,
            text="  📈 기관별 매매 동향 분석 (KRX)  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid", padx=10, pady=10,
        )
        outer.pack(fill="x", pady=4)

        # ── 1행: 필터 ──
        row1 = tk.Frame(outer, bg=self.bg_card)
        row1.pack(fill="x", pady=(0, 5))

        def lbl(parent, text):
            tk.Label(parent, text=text, font=("맑은 고딕", 9, "bold"),
                     bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(0, 3))

        def cb(parent, var, vals, w):
            c = ttk.Combobox(parent, textvariable=var, values=vals,
                             state="readonly", width=w, font=("맑은 고딕", 9))
            c.pack(side="left", padx=(0, 10))
            return c

        lbl(row1, "투자자:")
        self.inv_var = tk.StringVar(value="외국인")
        cb(row1, self.inv_var, list(INVESTOR_TYPES), 15)

        lbl(row1, "기간:")
        self.prd_var = tk.StringVar(value="1개월")
        cb(row1, self.prd_var, list(PERIODS), 7)

        lbl(row1, "시장:")
        self.mkt_var = tk.StringVar(value="KOSPI")
        cb(row1, self.mkt_var, list(MARKETS), 14)

        lbl(row1, "방향:")
        self.dir_var = tk.StringVar(value="순매수 상위")
        cb(row1, self.dir_var, TRADE_DIRS, 11)

        self.fetch_btn = tk.Button(
            row1, text="🔍 조회",
            font=("맑은 고딕", 9, "bold"), bg=self.primary, fg=self.text_light,
            bd=0, relief="flat", cursor="hand2", padx=12, pady=4,
            command=self._load_thread,
        )
        self.fetch_btn.pack(side="left", padx=(0, 10))

        self.status_lbl = tk.Label(
            row1, text="투자자·기간·시장 선택 후 조회하세요.",
            font=("맑은 고딕", 8), bg=self.bg_card, fg=self.text_muted,
        )
        self.status_lbl.pack(side="left")

        # ── 2행: 요약 ──
        self.summary_lbl = tk.Label(
            outer, text="", font=("맑은 고딕", 9, "bold"),
            bg=self.bg_card, fg=self.text_dark, anchor="w",
        )
        self.summary_lbl.pack(fill="x", pady=(0, 4))

        # ── 3행: Treeview ──
        tv_frame = tk.Frame(outer, bg=self.bg_card)
        tv_frame.pack(fill="x", pady=(0, 6))

        col_names = [c[0] for c in COLS]
        self.tree = ttk.Treeview(tv_frame, columns=col_names, show="headings",
                                  selectmode="extended", height=10)
        for col, width, anchor, field in COLS:
            if field:
                self.tree.heading(col, text=col,
                                  command=lambda f=field: self._sort_by(f))
            else:
                self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=False)

        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("buy",  foreground="#D62728")
        self.tree.tag_configure("sell", foreground="#1565C0")
        self.tree.tag_configure("odd",  background="#F7F3EC")

        # ── 4행: 버튼 ──
        row4 = tk.Frame(outer, bg=self.bg_card)
        row4.pack(fill="x")

        for text, cmd, px in [
            ("상위 5 선택", self._sel_top5,  (0, 6)),
            ("전체 선택",   self._sel_all,   (0, 6)),
            ("선택 해제",   self._sel_none,  (0, 18)),
        ]:
            tk.Button(row4, text=text, font=("맑은 고딕", 9),
                      bg=self.bg_input, fg=self.text_dark,
                      bd=1, relief="solid", cursor="hand2", padx=8, pady=5,
                      command=cmd).pack(side="left", padx=px)

        tk.Button(
            row4, text="📊  선택 종목 리포트 생성",
            font=("맑은 고딕", 10, "bold"),
            bg=self.btn_rss, fg=self.text_light,
            activebackground=self.tertiary_hov, activeforeground=self.text_light,
            bd=0, relief="flat", cursor="hand2", padx=16, pady=6,
            command=self._send_to_report,
        ).pack(side="left")

    # ─── 데이터 조회 ─────────────────────────────────────────────────
    def _load_thread(self):
        self.fetch_btn.configure(state="disabled", text="조회 중…")
        self.status_lbl.configure(text="KRX 데이터 조회 중…", fg=self.text_muted)
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            inv_code = INVESTOR_TYPES[self.inv_var.get()]
            prd_days = PERIODS[self.prd_var.get()]
            mkt_key  = self.mkt_var.get()
            mkt_id   = MARKETS[mkt_key]
            reverse  = (self.dir_var.get() == "순매수 상위")

            if mkt_id == "ALL":
                rows = _fetch_ranking("STK", inv_code, prd_days) + \
                       _fetch_ranking("KSQ", inv_code, prd_days)
            else:
                rows = _fetch_ranking(mkt_id, inv_code, prd_days)

            self._stocks = sorted(
                rows,
                key=lambda r: _as_int(r.get("NETBUY_TRDVAL", "0")),
                reverse=reverse,
            )[:50]
            self._sort_col = "NETBUY_TRDVAL"
            self._sort_rev = reverse

            self.root.after(0, self._populate)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.status_lbl.configure(
                text=f"오류: {err}", fg="#E63B2E"))
        finally:
            self.root.after(0, lambda: self.fetch_btn.configure(
                state="normal", text="🔍 조회"))

    # ─── Treeview 렌더링 ─────────────────────────────────────────────
    def _populate(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        if not self._stocks:
            self.status_lbl.configure(text="조회 결과 없음", fg=self.text_muted)
            self.summary_lbl.configure(text="")
            return

        total_buy = total_sell = 0
        for i, s in enumerate(self._stocks):
            code    = s.get("ISU_SRT_CD", "")
            name    = s.get("ISU_ABBRV", "")
            vol     = _as_int(s.get("NETBUY_TRDVOL", "0"))
            val_mil = _as_int(s.get("NETBUY_TRDVAL", "0"))
            close_v = _as_int(s.get("CLSPRC", "0"))
            fluc    = _as_float(s.get("FLUC_RT", "0"))
            trd_val = _as_int(s.get("ACC_TRDVAL", "0"))

            if val_mil >= 0:
                total_buy  += val_mil
            else:
                total_sell += abs(val_mil)

            tags = ("buy" if val_mil >= 0 else "sell",) + (("odd",) if i % 2 else ())
            arrow = "▲" if fluc > 0 else ("▼" if fluc < 0 else "−")

            self.tree.insert("", "end", iid=str(i), tags=tags,
                values=(
                    i + 1,
                    name,
                    code,
                    f"{vol:+,}",
                    _fmt_amount(val_mil),
                    f"{close_v:,}" if close_v else "",
                    f"{arrow} {abs(fluc):.2f}%",
                    _fmt_amount(trd_val),
                ))

        inv  = self.inv_var.get()
        prd  = self.prd_var.get()
        mkt  = self.mkt_var.get()
        drct = self.dir_var.get()
        n    = len(self._stocks)

        self.status_lbl.configure(
            text=f"{inv} · {prd} · {mkt} · {drct}  ({n}종목)",
            fg=self.text_dark)

        net = total_buy - total_sell
        self.summary_lbl.configure(
            text=(f"  순매수 합계 {_fmt_amount(total_buy)}  |  "
                  f"순매도 합계 -{_fmt_amount(total_sell)[1:]}  |  "
                  f"순매수 총계 {_fmt_amount(net)}"),
            fg="#D62728" if net >= 0 else "#1565C0",
        )

    # ─── 컬럼 정렬 ───────────────────────────────────────────────────
    def _sort_by(self, field: str):
        if self._sort_col == field:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = field
            self._sort_rev = True
        self._stocks.sort(
            key=lambda r: _as_int(r.get(field, "0")),
            reverse=self._sort_rev,
        )
        self._populate()

    # ─── 선택 헬퍼 ───────────────────────────────────────────────────
    def _sel_top5(self):
        self.tree.selection_set(self.tree.get_children()[:5])

    def _sel_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _sel_none(self):
        self.tree.selection_remove(self.tree.get_children())

    # ─── 리포트 연동 ─────────────────────────────────────────────────
    def _send_to_report(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(
                "선택 없음",
                "리포트에 포함할 종목을 선택해 주세요.\n(Ctrl+클릭으로 복수 선택 가능)")
            return

        tickers = []
        for iid in selected:
            s      = self._stocks[int(iid)]
            code   = s.get("ISU_SRT_CD", "")
            suffix = s.get("_sfx", "KS")
            if code:
                tickers.append(f"{code}.{suffix}")

        if not tickers:
            messagebox.showwarning("오류", "종목 코드를 확인할 수 없습니다.")
            return

        self.report_section.ticker_entry.delete(0, "end")
        self.report_section.ticker_entry.insert(0, ", ".join(tickers))
        self.report_section.market_var.set("🇰🇷 한국")
        self.report_section.start_report_thread()
