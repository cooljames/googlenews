# pyright: reportMissingImports=false
"""
stock_report.py — 주식/ETF 뉴스 리포트 섹션
티커 입력 → yfinance 가격·등락 수집 + 구글 뉴스 RSS → matplotlib 그래프
→ Gemini 종합 분석 → Desktop/lists/ 에 HTML 리포트 + charts/ 에 PNG 저장
"""
import re
import json
import html
import threading
import traceback
import webbrowser
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dtime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("Agg")  # GUI 스레드와 분리된 백엔드
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import yfinance as yf
from google import genai
from google.genai import types

try:
    from standalone_poster import load_config
except ImportError:
    pass  # 오류는 gui_app.py 에서 처리

KST = timezone(timedelta(hours=9))

# 한글 깨짐 방지 (Windows 기본 폰트)
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

# 기간: 표시명 → (yfinance period, 뉴스 검색 when:)
PERIOD_PRESETS = {
    "1주": ("7d",  "7d"),
    "1개월": ("1mo", "14d"),
    "3개월": ("3mo", "14d"),
    "6개월": ("6mo", "30d"),
    "1년":  ("1y",  "30d"),
    "3년":  ("3y",  "30d"),
    "5년":  ("5y",  "30d"),
    "10년": ("10y", "30d"),
    "전체": ("max", "30d"),
}

MARKET_PRESETS = {
    "🇰🇷 한국": ("ko",    "KR", "KR:ko"),
    "🇺🇸 미국": ("en-US", "US", "US:en"),
}

# 차트 공통 색상 팔레트 — 12색, 색상환을 고르게 분산해 인접 종목 구별 용이
PALETTE = [
    "#D62728",  # [0] vivid red        (warm)
    "#1969CF",  # [1] vivid blue       (cool)  comp-red
    "#2CA02C",  # [2] vivid green      (cool)
    "#FF6B00",  # [3] vivid orange     (warm)  comp-blue
    "#8B00D4",  # [4] vivid violet     (cool)  comp-orange
    "#00A67E",  # [5] vivid teal       (cool)  comp-violet
    "#E8005A",  # [6] vivid hot-pink   (warm)  comp-teal
    "#00A8CC",  # [7] vivid cyan       (cool)  comp-pink
    "#CC8800",  # [8] dark amber       (warm)  comp-cyan
    "#5B3CC4",  # [9] vivid indigo     (cool)  comp-amber
    "#3CB62A",  # [10] vivid lime      (warm)
    "#0055AA",  # [11] deep navy       (cool)  comp-lime
]

# 한국 종목명·거래소 실시간 조회 (네이버 증권 모바일 API)
NAVER_STOCK_API = "https://m.stock.naver.com/api/stock/{code}/basic"


def _get_desktop() -> Path:
    """어떤 Windows PC에서도 실제 바탕화면 폴더를 반환 (OneDrive 동기화 대응)."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as k:
            return Path(winreg.QueryValueEx(k, "Desktop")[0])
    except Exception:
        pass
    for candidate in [
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "Desktop",
    ]:
        if candidate.exists():
            return candidate
    return Path.home() / "Desktop"


class StockReportSection:
    """주식/ETF 뉴스 리포트 섹션. build(container) 로 UI 구성."""

    def __init__(self, root: tk.Tk, theme: dict):
        self.root         = root
        self.bg_card      = theme["bg_card"]
        self.bg_input     = theme["bg_input"]
        self.text_light   = theme["text_light"]
        self.text_dark    = theme.get("text_dark", "#1A1A1A")
        self.text_muted   = theme["text_muted"]
        self.accent       = theme["accent"]
        self.hover_dark   = theme.get("hover_dark", "#E6B800")
        self.btn_rss      = theme["btn_rss"]
        self.tertiary_hov = theme.get("tertiary_hov", "#003DD6")
        self.primary      = theme.get("primary", "#1A1A1A")
        self.border_color = theme.get("border_color", "#1A1A1A")
        self._kr_cache: dict = {}  # 한국 종목 실시간 조회 캐시 (code → {name, suffix})

    # ──────────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────────
    def build(self, container: tk.Frame) -> None:
        frame = tk.LabelFrame(
            container,
            text="  📈 주식 / ETF 뉴스 리포트  ",
            font=("맑은 고딕", 10, "bold"),
            bg=self.bg_card, fg=self.text_dark,
            bd=3, relief="solid", padx=10, pady=10,
        )
        frame.pack(fill="x", pady=4)

        # 안내
        tk.Label(
            frame,
            text="티커를 쉼표로 구분해 입력하세요.  예) 한국: 005930.KS, 069500.KS  /  미국: AAPL, SPY, QQQ",
            font=("맑은 고딕", 8),
            bg=self.bg_card, fg=self.text_muted, anchor="w",
        ).pack(fill="x", pady=(0, 6))

        # 입력 행: 시장 / 기간
        opt_row = tk.Frame(frame, bg=self.bg_card)
        opt_row.pack(fill="x", pady=(0, 4))

        tk.Label(opt_row, text="시장:", font=("맑은 고딕", 9, "bold"),
                 bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(0, 4))
        self.market_var = tk.StringVar(value="🇰🇷 한국")
        self.market_cb = ttk.Combobox(opt_row, textvariable=self.market_var,
                     values=list(MARKET_PRESETS.keys()),
                     state="readonly", width=9, font=("맑은 고딕", 9)
                     )
        self.market_cb.pack(side="left", padx=(0, 10))
        self.market_cb.bind("<<ComboboxSelected>>", self._on_market_change)

        tk.Label(opt_row, text="기간:", font=("맑은 고딕", 9, "bold"),
                 bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(0, 4))
        self.period_var = tk.StringVar(value="1개월")
        ttk.Combobox(opt_row, textvariable=self.period_var,
                     values=list(PERIOD_PRESETS.keys()),
                     state="readonly", width=8, font=("맑은 고딕", 9)
                     ).pack(side="left")

        tk.Label(opt_row, text="뉴스 필터:", font=("맑은 고딕", 9, "bold"),
                 bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(10, 4))
        self.news_filter_var = tk.StringVar(value="장후")
        ttk.Combobox(opt_row, textvariable=self.news_filter_var,
                     values=["장전", "장중", "장후", "실시간(1시간 이내)", "6시간", "12시간", "24시간"],
                     state="readonly", width=16, font=("맑은 고딕", 9)
                     ).pack(side="left")

        # 티커 입력
        ticker_row = tk.Frame(frame, bg=self.bg_card)
        ticker_row.pack(fill="x", pady=(0, 6))
        tk.Label(ticker_row, text="티커:", font=("맑은 고딕", 9, "bold"),
                 bg=self.bg_card, fg=self.text_dark).pack(side="left", padx=(0, 4))
        self.ticker_entry = tk.Entry(
            ticker_row, bg=self.bg_input, fg=self.text_dark,
            insertbackground=self.text_dark, bd=2, relief="solid",
            font=("Consolas", 10),
        )
        self.ticker_entry.pack(side="left", fill="x", expand=True)
        self.ticker_entry.insert(0, "005930.KS, 069500.KS")

        # 상태 레이블
        self.status_lbl = tk.Label(
            frame,
            text="티커를 입력하고 [리포트 생성] 버튼을 누르세요.",
            font=("맑은 고딕", 8), bg=self.bg_card, fg=self.text_muted, anchor="w",
        )
        self.status_lbl.pack(fill="x", pady=(0, 6))

        # 생성 버튼 + 열어보기 버튼
        btn_row = tk.Frame(frame, bg=self.bg_card)
        btn_row.pack(fill="x")

        self.gen_btn = tk.Button(
            btn_row,
            text="📊  데이터·뉴스 수집 → 표·그래프·분석 리포트 생성",
            font=("맑은 고딕", 11, "bold"),
            bg=self.btn_rss, fg=self.text_light,
            activebackground=self.tertiary_hov, activeforeground=self.text_light,
            bd=0, relief="flat", cursor="hand2", padx=20, pady=12,
            command=self.start_report_thread,
        )
        self.gen_btn.pack(side="left", fill="x", expand=True)
        self.gen_btn.bind("<Enter>", lambda e: self._hover(e, self.tertiary_hov))
        self.gen_btn.bind("<Leave>", lambda e: self._hover(e, self.btn_rss))

        self.open_btn = tk.Button(
            btn_row,
            text="🌐 열어보기",
            font=("맑은 고딕", 10, "bold"),
            bg=self.primary, fg=self.text_light,
            activebackground=self.accent, activeforeground=self.text_dark,
            bd=0, relief="flat", cursor="hand2", padx=14, pady=12,
            state="disabled",
            command=self._open_report,
        )
        self.open_btn.pack(side="left", padx=(6, 0))
        self.open_btn.bind("<Enter>", lambda e: self._hover(e, self.accent))
        self.open_btn.bind("<Leave>", lambda e: self._hover(e, self.primary))
        self.last_html_path: str = ""
        self._on_market_change()

    def _hover(self, event, color: str) -> None:
        if event.widget["state"] != "disabled":
            event.widget["background"] = color

    # ──────────────────────────────────────────────
    # 실행
    # ──────────────────────────────────────────────
    def start_report_thread(self) -> None:
        raw = self.ticker_entry.get().strip()
        market = self.market_var.get()
        tickers = [
            self._normalize_ticker(t, market)
            for t in raw.split(",") if t.strip()
        ]
        if not tickers:
            messagebox.showwarning("입력 오류", "티커를 하나 이상 입력해 주세요.")
            return

        cfg = load_config()
        if not cfg.get("gemini_api_key"):
            messagebox.showwarning("설정 오류",
                "Gemini API Key가 설정되지 않았습니다.\n설정 탭에서 입력해 주세요.")
            return

        self.gen_btn.configure(state="disabled", text="리포트 생성 중... ⏳", bg="#4A4A4A")
        threading.Thread(
            target=self._run_report, args=(cfg, tickers), daemon=True
        ).start()

    def _run_report(self, cfg: dict, tickers: list) -> None:
        try:
            print("\n" + "=" * 60)
            print(f"📈 주식 리포트 시작 — 티커: {', '.join(tickers)}")

            period_label = self.period_var.get()
            yf_period, news_when = PERIOD_PRESETS.get(period_label, ("1mo", "14d"))
            market = self.market_var.get()

            # 1) 가격 데이터 수집
            self._set_status("가격 데이터 수집 중...")
            price_rows, price_series = self._collect_prices(tickers, yf_period, market)
            if not price_rows:
                raise RuntimeError("가격 데이터를 가져오지 못했습니다. 티커를 확인하세요.")

            # 2) 뉴스 수집
            self._set_status("뉴스 헤드라인 수집 중...")
            news_map = self._collect_news(price_rows, market, news_when)

            # 3) 차트 생성
            self._set_status("그래프 생성 중...")
            now = datetime.now(KST)
            desktop    = _get_desktop()
            charts_dir = desktop / "lists" / "charts"
            charts_dir.mkdir(parents=True, exist_ok=True)
            stamp = now.strftime("%Y-%m-%d_%H-%M")
            line_png = charts_dir / f"price_{stamp}.png"
            bar_png  = charts_dir / f"return_{stamp}.png"
            # 두 그래프에서 종목별로 동일한 색을 쓰도록 색상 맵 구성
            color_map = {
                r["symbol"]: PALETTE[i % len(PALETTE)]
                for i, r in enumerate(price_rows)
            }
            # 그래프 라벨: 한글 종목명만 사용 (코드 제외)
            name_map = {r["symbol"]: r["name"] for r in price_rows}
            self._make_line_chart(price_series, line_png, period_label, color_map, name_map)
            self._make_bar_chart(price_rows, bar_png, period_label, color_map, name_map)

            # 3-1) 시장 지수 스냅샷
            self._set_status("시장 지수 데이터 수집 중...")
            try:
                index_data = self._collect_market_data(market)
                print("  ✓ 시장 지수 완료")
            except Exception as _me:
                index_data = []
                print(f"  [경고] 시장 지수 생략: {_me}")

            # 4) Gemini 분석
            self._set_status("Gemini 종합 분석 중...")
            analysis = self._gen_analysis(
                cfg, price_rows, news_map, period_label, market, self.news_filter_var.get()
            )

            # 5) HTML 리포트 저장 (파일명에 한글 종목명 포함)
            self._set_status("HTML 리포트 저장 중...")
            lists_dir = desktop / "lists"
            lists_dir.mkdir(parents=True, exist_ok=True)
            names_label = self._filename_names(price_rows)
            html_path = lists_dir / f"{stamp} 주식리포트 {names_label}.html"
            self._write_html(
                html_path, price_rows, news_map, analysis,
                line_png, bar_png, index_data, period_label, market, now,
                self.news_filter_var.get()
            )

            fp = str(html_path)
            self.last_html_path = fp
            self.root.after(0, lambda: self.open_btn.configure(state="normal"))
            print(f"💾 저장 완료: {fp}\n" + "=" * 60)
            self.root.after(0, lambda: messagebox.showinfo(
                "리포트 생성 완료",
                f"주식 뉴스 리포트가 저장되었습니다!\n\n📁 {fp}\n\n"
                "[🌐 열어보기] 버튼으로 브라우저에서 바로 열 수 있습니다.",
            ))

        except Exception as e:
            err = str(e)
            print(f"\n❌ 리포트 생성 오류:\n{err}\n{traceback.format_exc()}")
            self.root.after(0, lambda: messagebox.showerror(
                "리포트 실패", f"리포트 생성 중 오류가 발생했습니다:\n\n{err}"))
        finally:
            self.root.after(0, lambda: self.gen_btn.configure(
                state="normal",
                text="📊  데이터·뉴스 수집 → 표·그래프·분석 리포트 생성",
                bg=self.btn_rss,
            ))

    def _set_status(self, msg: str) -> None:
        print(f"  · {msg}")
        self.root.after(0, lambda: self.status_lbl.configure(text=msg))

    def _filename_names(self, price_rows: list) -> str:
        """파일명용 한글 종목명 문자열. 예: '삼성전자·HK이노엔' (4개 초과 시 '외 N')."""
        names = [r["name"] for r in price_rows]
        shown = names[:4]
        label = "·".join(shown)
        if len(names) > 4:
            label += f" 외 {len(names) - 4}"
        label = re.sub(r'[\\/:*?"<>|]', "", label).strip()
        return label[:80] or f"{len(price_rows)}종목"

    def _open_report(self) -> None:
        """가장 최근 저장한 HTML 리포트를 기본 브라우저로 연다."""
        if self.last_html_path and Path(self.last_html_path).exists():
            webbrowser.open(Path(self.last_html_path).as_uri())
        else:
            messagebox.showinfo("열어보기", "먼저 리포트를 생성해 주세요.")

    # ──────────────────────────────────────────────
    # 티커 정규화 / 다운로드
    # ──────────────────────────────────────────────
    def _lookup_kr(self, code: str):
        """네이버 증권에서 한국 종목의 한글명·거래소를 실시간 조회 (캐시).
        Returns {'name': 한글명, 'suffix': '.KS'|'.KQ'} 또는 None."""
        code = re.sub(r"\.[A-Z]+$", "", code.strip().upper())
        if not re.fullmatch(r"\d{4,6}", code):
            return None
        if code in self._kr_cache:
            return self._kr_cache[code]

        result = None
        try:
            req = urllib.request.Request(
                NAVER_STOCK_API.format(code=code),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            name = (data.get("stockName") or "").strip()
            ex   = data.get("stockExchangeType") or {}
            ex_code = ex.get("code") if isinstance(ex, dict) else ex
            if name:
                result = {
                    "name":   name,
                    "suffix": ".KQ" if ex_code == "KQ" else ".KS",
                }
        except Exception as e:
            print(f"  [경고] {code} 종목명 실시간 조회 실패: {e}")

        self._kr_cache[code] = result
        return result

    def _normalize_ticker(self, raw: str, market: str) -> str:
        """'005930' 처럼 코드만 입력해도 한국 시장이면 실시간 조회로 .KS/.KQ 부착."""
        sym = raw.strip().upper()
        if market == "🇰🇷 한국" and re.fullmatch(r"\d{4,6}", sym):
            info = self._lookup_kr(sym)
            return f"{sym}{info['suffix']}" if info else f"{sym}.KS"
        return sym

    def _kr_candidates(self, sym: str) -> list:
        """한국 코드 심볼의 거래소 후보. 실시간 조회로 거래소가 확인되면 그것만,
        실패하면 .KS / .KQ 둘 다 검증 대상으로 반환."""
        m = re.fullmatch(r"(\d{4,6})\.(?:KS|KQ)", sym)
        if not m:
            return [sym]
        code = m.group(1)
        info = self._lookup_kr(code)
        if info:
            return [f"{code}{info['suffix']}"]
        return [f"{code}.KS", f"{code}.KQ"]

    def _download_history(self, sym: str, yf_period: str):
        """심볼로 시세를 받되, 거래소를 확인할 수 없는 한국 코드는
        .KS/.KQ 후보 중 데이터가 있는 거래소를 선택한다.
        Returns: (실제로 데이터를 받은 심볼, hist DataFrame|None)."""
        candidates = self._kr_candidates(sym)
        for cand in candidates:
            try:
                h = yf.Ticker(cand).history(period=yf_period, auto_adjust=False)
                if h is not None and not h.empty:
                    return cand, h
            except Exception as e:
                print(f"  [경고] {cand} 다운로드 실패: {e}")
        return sym, None

    # ──────────────────────────────────────────────
    # 데이터 수집
    # ──────────────────────────────────────────────
    def _collect_prices(self, tickers: list, yf_period: str, market: str = "🇰🇷 한국"):
        """yfinance 로 가격 수집 → (요약행 리스트, {티커: 종가 시리즈})."""
        rows, series = [], {}
        for sym in tickers:
            try:
                sym, hist = self._download_history(sym, yf_period)
                if hist is None or hist.empty:
                    print(f"  [경고] {sym}: 데이터 없음 (건너뜀)")
                    continue
                tk_obj = yf.Ticker(sym)

                close = hist["Close"].dropna()
                if close.empty:
                    continue

                # 장중 실시간 가격 데이터 가져오기
                live_price = None
                live_volume = None
                try:
                    if self._is_market_active(market):
                        fast = tk_obj.fast_info
                        if fast and hasattr(fast, "last_price") and fast.last_price:
                            live_price = float(fast.last_price)
                        if fast and hasattr(fast, "last_volume") and fast.last_volume:
                            live_volume = int(fast.last_volume)
                except Exception:
                    pass

                close_list = list(close.values)
                if live_price is not None:
                    close_list[-1] = live_price
                    close.iloc[-1] = live_price

                first = float(close_list[0])
                last  = float(close_list[-1])
                prev  = float(close_list[-2]) if len(close_list) >= 2 else first

                try:
                    if self._is_market_active(market):
                        fast = tk_obj.fast_info
                        if fast and hasattr(fast, "previous_close") and fast.previous_close:
                            prev = float(fast.previous_close)
                except Exception:
                    pass

                day_chg    = (last / prev - 1) * 100 if prev else 0.0
                period_chg = (last / first - 1) * 100 if first else 0.0
                
                volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist else 0
                if live_volume is not None:
                    volume = live_volume

                # 기간 고가/저가는 장중 High/Low 기준 (실제 최고·최저가)
                high = float(hist["High"].max()) if "High" in hist else last
                low  = float(hist["Low"].min())  if "Low"  in hist else last
                if live_price is not None:
                    high = max(high, live_price)
                    low = min(low, live_price)

                # 당일 시세 (네이버 일간 시세 형식)
                day_open = float(hist["Open"].iloc[-1]) if "Open" in hist else last
                day_high = float(hist["High"].iloc[-1]) if "High" in hist else last
                day_low  = float(hist["Low"].iloc[-1])  if "Low"  in hist else last
                if live_price is not None:
                    day_high = max(day_high, live_price)
                    day_low = min(day_low, live_price)

                name = self._ticker_name(tk_obj, sym)
                try:
                    mktcap = int(getattr(tk_obj.fast_info, "market_cap", 0) or 0)
                except Exception:
                    mktcap = 0
                rows.append({
                    "symbol":      sym,
                    "name":        name,
                    "last":        last,
                    "last_dt":     self._fmt_dt(close.index[-1], market),
                    "day_chg":     day_chg,
                    "period_chg":  period_chg,
                    "high":        high,
                    "low":         low,
                    "volume":      volume,
                    "mktcap":      mktcap,
                    # 당일 시세 스냅샷
                    "prev_close":  prev,
                    "diff":        last - prev,
                    "day_open":    day_open,
                    "day_high":    day_high,
                    "day_low":     day_low,
                    "trade_value": volume * last,
                })
                series[sym] = close
                print(f"  ✓ {sym} ({name}): 종가 {last:,.2f}  기간 {period_chg:+.2f}%")
            except Exception as e:
                print(f"  [경고] {sym} 수집 실패: {e}")
        return rows, series

    def _ticker_name(self, tk_obj, sym: str) -> str:
        # 1) 한국 종목: 네이버 실시간 한글명
        info = self._lookup_kr(sym)
        if info and info["name"]:
            return info["name"]
        # 2) yfinance 영문명 (주로 미국 종목)
        try:
            meta = tk_obj.info or {}
            return meta.get("longName") or meta.get("shortName") or sym
        except Exception:
            return sym

    def _is_market_active(self, market: str) -> bool:
        now_kst = datetime.now(KST)
        is_weekday = now_kst.weekday() < 5
        if not is_weekday:
            return False
            
        if market == "🇰🇷 한국":
            return dtime(9, 0) <= now_kst.time() <= dtime(15, 30)
        elif market == "🇺🇸 미국":
            now_et = self._kst_to_et(now_kst)
            if now_et.weekday() >= 5:
                return False
            return dtime(9, 30) <= now_et.time() <= dtime(16, 0)
        return False

    def _on_market_change(self, event=None):
        market = self.market_var.get()
        is_active = self._is_market_active(market)
        self.news_filter_var.set("장중" if is_active else "장후")

    def _fmt_dt(self, ts, market: str = "🇰🇷 한국") -> str:
        """최종 거래일 + 시간으로 표기.
        장중(실시간)이면 현재 시각으로 표기하고, 그 외에는 장 마감 시간으로 표기."""
        now_kst = datetime.now(KST)
        if self._is_market_active(market):
            if market == "🇺🇸 미국":
                now_et = self._kst_to_et(now_kst)
                return now_et.strftime("%Y-%m-%d %H:%M") + " (ET)"
            else:
                return now_kst.strftime("%Y-%m-%d %H:%M") + " (KST)"
        try:
            d = ts.strftime("%Y-%m-%d")
        except Exception:
            d = str(ts)[:10]
        close_time = "16:00" if market == "🇺🇸 미국" else "15:30"
        return f"{d} {close_time}"

    def _kst_to_et(self, dt_kst: datetime) -> datetime:
        from datetime import date
        dt_utc = dt_kst.astimezone(timezone.utc)
        y, m, d = dt_utc.year, dt_utc.month, dt_utc.day
        is_dst = False
        if 4 <= m <= 10:
            is_dst = True
        elif m == 3:
            first_day_w = date(y, 3, 1).weekday()
            first_sun = 1 + (6 - first_day_w) % 7
            second_sun = first_sun + 7
            if d > second_sun or (d == second_sun and dt_utc.hour >= 7):
                is_dst = True
        elif m == 11:
            first_day_w = date(y, 11, 1).weekday()
            first_sun = 1 + (6 - first_day_w) % 7
            if d < first_sun or (d == first_sun and dt_utc.hour < 6):
                is_dst = True
                
        offset = timedelta(hours=-4) if is_dst else timedelta(hours=-5)
        return (dt_utc + offset).replace(tzinfo=None)

    def _is_in_filter(self, dt: datetime, filter_type: str, market: str, last_dt_str: str) -> bool:
        if not dt:
            return False
        
        now = datetime.now(KST)
        
        # 1. 상대 시간 필터
        if filter_type == "실시간(1시간 이내)":
            return now - timedelta(hours=1) <= dt <= now
        elif filter_type == "6시간":
            return now - timedelta(hours=6) <= dt <= now
        elif filter_type == "12시간":
            return now - timedelta(hours=12) <= dt <= now
        elif filter_type == "24시간":
            return now - timedelta(hours=24) <= dt <= now
            
        # 2. 거래 세션 기반 필터
        try:
            last_date = datetime.strptime(last_dt_str[:10], "%Y-%m-%d").date()
        except Exception:
            last_date = now.date()
            
        if market == "🇺🇸 미국":
            dt_local = self._kst_to_et(dt)
            open_time = datetime.combine(last_date, dtime(9, 30))
            close_time = datetime.combine(last_date, dtime(16, 0))
            prev_close_time = datetime.combine(last_date - timedelta(days=4), dtime(16, 0))
            
            if filter_type == "장전":
                return prev_close_time <= dt_local < open_time
            elif filter_type == "장중":
                return open_time <= dt_local <= close_time
            elif filter_type == "장후":
                return dt_local > close_time
        else: # "🇰🇷 한국"
            dt_local = dt.astimezone(KST).replace(tzinfo=None)
            open_time = datetime.combine(last_date, dtime(9, 0))
            close_time = datetime.combine(last_date, dtime(15, 30))
            prev_close_time = datetime.combine(last_date - timedelta(days=4), dtime(15, 30))
            
            if filter_type == "장전":
                return prev_close_time <= dt_local < open_time
            elif filter_type == "장중":
                return open_time <= dt_local <= close_time
            elif filter_type == "장후":
                return dt_local > close_time
                
        return False

    def _collect_news(self, price_rows: list, market: str, when: str) -> dict:
        """종목별 구글 뉴스 RSS 헤드라인 수집 → {symbol: [기사,...]}.
        선택한 뉴스 필터 조건에 부합하는 뉴스만 남긴다."""
        hl, gl, ceid = MARKET_PRESETS.get(market, MARKET_PRESETS["🇰🇷 한국"])
        out = {}
        filter_type = self.news_filter_var.get()
        for row in price_rows:
            sym = row["symbol"]
            name = row["name"]
            base = re.sub(r"\.[A-Z]+$", "", sym)
            query = name if name and name != sym else base
            q = f"{query} when:{when}" if when else query
            url = (
                f"https://news.google.com/rss/search?q={quote(q)}"
                f"&hl={hl}&gl={gl}&ceid={ceid}"
            )
            try:
                items = self._fetch_rss(url)
                fresh = [h for h in items if h.get("dt") and self._is_in_filter(h["dt"], filter_type, market, row["last_dt"])]
                out[sym] = fresh[:6]
                print(f"  ✓ {sym} 뉴스 필터({filter_type}) 적용 후 뉴스 {len(out[sym])}건")
            except Exception as e:
                print(f"  [경고] {sym} 뉴스 수집 실패: {e}")
                out[sym] = []
        return out

    def _fetch_rss(self, url: str) -> list:
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()

        root_el = ET.fromstring(raw)
        ns = (root_el.tag.split("}")[0] + "}") if root_el.tag.startswith("{") else ""
        channel = root_el.find(f"{ns}channel") or root_el

        def _text(item, tag):
            el = item.find(f"{ns}{tag}")
            return (el.text or "").strip() if el is not None else ""

        items = []
        for item in channel.findall(f"{ns}item"):
            pub = _text(item, "pubDate")
            try:
                dt   = parsedate_to_datetime(pub).astimezone(KST)
                disp = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt, disp = None, pub[:16]
            items.append({
                "title": _text(item, "title") or "(제목 없음)",
                "link":  _text(item, "link"),
                "date":  disp,
                "dt":    dt,
            })
        return items

    # ──────────────────────────────────────────────
    # 시장 지수 개요
    # ──────────────────────────────────────────────
    def _collect_market_data(self, market: str = "🇰🇷 한국"):
        """시장에 따라 주요 지수 스냅샷 → [{name, last, diff, pct}, ...]."""
        if market == "🇺🇸 미국":
            idx_cfg = [
                ("다우산업",   "^DJI"),
                ("나스닥종합", "^IXIC"),
                ("S&P 500",   "^GSPC"),
            ]
        else:
            idx_cfg = [
                ("코스피",    "^KS11"),
                ("코스닥",    "^KQ11"),
                ("코스피200", "^KS200"),
            ]
        index_data = []
        for name, sym in idx_cfg:
            try:
                h = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
                if h is not None and len(h) >= 2:
                    prev = float(h["Close"].iloc[-2])
                    last = float(h["Close"].iloc[-1])
                    diff = last - prev
                    pct  = (diff / prev * 100) if prev else 0
                    index_data.append({"name": name, "last": last, "diff": diff, "pct": pct})
            except Exception as e:
                print(f"  [경고] {name} 지수: {e}")
        return index_data

    # ──────────────────────────────────────────────
    # 차트
    # ──────────────────────────────────────────────
    def _make_line_chart(self, series: dict, path: Path, period_label: str,
                         color_map: dict, name_map: dict) -> None:
        """기간 시작=100 으로 리베이스한 종가 추이. 라벨은 차트 내부 우측에 표기."""
        import matplotlib.ticker as mticker

        class _KoDateFmt(mticker.Formatter):
            """틱 간격에 따라 한국어 날짜 자동 선택 (연/월/월일)."""
            def __call__(self, x, pos=None):
                try:
                    dt = mdates.num2date(x)
                    ticks = self.axis.get_ticklocs()
                    span = (ticks[-1] - ticks[0]) if len(ticks) > 1 else 1000
                    if span > 500:            # 1년 초과: 연도 + 월
                        return f"{dt.year}년\n{dt.month}월"
                    elif span > 150:          # 5개월 초과: 월만
                        return f"{dt.month}월"
                    else:                     # 5개월 이하: 월/일 (중복 방지)
                        return f"{dt.month}/{dt.day}"
                except Exception:
                    return ""

        import numpy as np

        def _cubic_smooth(x: np.ndarray, y: np.ndarray, n_out: int = 400):
            """가우시안 사전 스무딩 후 자연 3차 스플라인. 과도한 진동을 억제."""
            n = len(x)
            if n < 4:
                return x, y
            # 가우시안 스무딩 (sigma = 데이터 길이/15, 최소 2) — 값이 클수록 곡선 완만
            sigma  = max(2.0, n / 15.0)
            radius = int(sigma * 3)
            kk = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
            kk /= kk.sum()
            y_sm = np.convolve(np.pad(y, radius, mode="edge"), kk, mode="valid")
            # 스무딩된 데이터로 자연 3차 스플라인
            h = np.diff(x).astype(float)
            A = np.zeros((n, n))
            b = np.zeros(n)
            A[0, 0] = A[-1, -1] = 1.0
            for i in range(1, n - 1):
                A[i, i-1] = h[i-1]
                A[i, i]   = 2.0 * (h[i-1] + h[i])
                A[i, i+1] = h[i]
                b[i] = 6.0 * ((y_sm[i+1]-y_sm[i])/h[i] - (y_sm[i]-y_sm[i-1])/h[i-1])
            M = np.linalg.solve(A, b)
            x_fine = np.linspace(x[0], x[-1], n_out)
            y_fine = np.empty(n_out)
            for ki, xi in enumerate(x_fine):
                i  = min(int(np.searchsorted(x, xi, side="right")) - 1, n - 2)
                t  = xi - x[i]
                hi = h[i]
                y_fine[ki] = (
                    (M[i+1] - M[i]) / (6*hi) * t**3
                    + M[i] / 2 * t**2
                    + ((y_sm[i+1]-y_sm[i])/hi - hi*(2*M[i]+M[i+1])/6) * t
                    + y_sm[i]
                )
            return x_fine, y_fine

        fig, ax = plt.subplots(figsize=(9.6, 4.6), dpi=110)
        ends = []
        for sym, close in series.items():
            base = float(close.iloc[0])
            if not base:
                continue
            rebased = close / base * 100
            color = color_map.get(sym)
            x_num = np.array(mdates.date2num(close.index.to_pydatetime()))
            y_vals = rebased.values.astype(float)
            x_s, y_s = _cubic_smooth(x_num, y_vals)
            ax.plot(x_s, y_s, linewidth=1.3, color=color)
            ends.append((float(y_s[-1]), name_map.get(sym, sym), color, x_s[-1]))

        ax.axhline(100, color="#999999", linewidth=1, linestyle="--")
        ax.set_title(f"종가 추이 (기간 시작=100 기준)  ·  {period_label}", fontweight="bold")
        ax.set_ylabel("리베이스 지수")
        ax.tick_params(axis="both", labelsize=9)
        ax.grid(True, alpha=0.3)

        locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(_KoDateFmt())

        # 선 끝 라벨 — 차트 내부 우측에 세로 분산, 둥근 테두리 박스
        ymin, ymax = ax.get_ylim()
        min_gap = (ymax - ymin) / 16.0
        ends.sort(key=lambda e: e[0])
        placed_y = []
        for last_y, *_ in ends:
            y = last_y
            if placed_y and y < placed_y[-1] + min_gap:
                y = placed_y[-1] + min_gap
            placed_y.append(y)
        if placed_y:
            # 라벨 상자가 y축 경계를 벗어나지 않도록 상하 패딩 추가
            ax.set_ylim(min(ymin, placed_y[0] - min_gap * 0.6), max(ymax, placed_y[-1] + min_gap * 0.6))

        # x축 우측을 연장하여 라벨이 축 상자 안쪽에 들어가도록 함
        xmin, xmax_data = ax.get_xlim()
        x_span = xmax_data - xmin
        ax.set_xlim(xmin, xmax_data + x_span * 0.16)
        
        fixed_ticks = [t for t in ax.get_xticks() if xmin <= t <= xmax_data]
        ax.set_xticks(fixed_ticks)   # 연장 영역에 새 눈금 방지

        # 라벨 시작 X 좌표: 데이터 끝에서 1.5% 우측 (좌측 정렬로 안쪽 배치)
        x_text = xmax_data + x_span * 0.015

        for (last_y, name, color, last_x), y in zip(ends, placed_y):
            ax.annotate(
                name,
                xy=(last_x, last_y),                   # 선 끝 (정밀한 스무딩 좌표)
                xytext=(x_text, y),                    # 라벨 위치 (데이터 좌표, 좌측 정렬)
                textcoords="data",
                va="center", ha="left",
                fontsize=8, fontweight="bold", color=color,
                annotation_clip=True,                  # 축 영역 내에만 표시
                arrowprops=dict(arrowstyle="-", color=color, lw=0.6, alpha=0.5),
                bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                          edgecolor=color, linewidth=1.3, alpha=0.90),
            )

        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)

    def _make_bar_chart(self, rows: list, path: Path, period_label: str,
                        color_map: dict, name_map: dict) -> None:
        """종목별 기간 등락률 막대 차트. x축 라벨은 한글 이름만, 사선으로 표기."""
        fig, ax = plt.subplots(figsize=(9.6, 4.6), dpi=110)
        syms   = [r["symbol"] for r in rows]
        labels = [name_map.get(s, s) for s in syms]   # 한글 이름만
        vals   = [r["period_chg"] for r in rows]
        colors = [color_map.get(s) for s in syms]      # 라인차트와 동일 색
        pos    = range(len(syms))
        bars = ax.bar(pos, vals, color=colors)
        ax.set_xticks(list(pos))
        ax.set_xticklabels(labels, fontsize=9, rotation=35, ha="right")
        ax.axhline(0, color="#1A1A1A", linewidth=1)
        ax.set_title(f"기간 등락률(%)  ·  {period_label}", fontweight="bold")
        ax.set_ylabel("등락률 (%)")
        ax.grid(True, axis="y", alpha=0.3)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v,
                    f"{v:+.1f}%", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=9, fontweight="bold")
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)

    # ──────────────────────────────────────────────
    # Gemini 분석
    # ──────────────────────────────────────────────
    def _gen_analysis(self, cfg, price_rows, news_map, period_label, market, news_filter) -> str:
        model_id = cfg.get("gemini_model", "gemini-3.1-flash-lite")
        client   = genai.Client(api_key=cfg["gemini_api_key"])

        is_us = (market == "🇺🇸 미국")
        def pfmt(v): return f"{v:,.2f}" if is_us else f"{v:,.0f}"

        price_txt = "\n".join(
            f"- {r['name']}({r['symbol']}): "
            f"현재 종가 {pfmt(r['last'])} (장 최종 {r['last_dt']}), "
            f"일간 {r['day_chg']:+.2f}%, 기간 {r['period_chg']:+.2f}%, "
            f"기간고가 {pfmt(r['high'])}, 기간저가 {pfmt(r['low'])}"
            for r in price_rows
        )
        news_txt = ""
        for r in price_rows:
            sym = r["symbol"]
            heads = news_map.get(sym, [])
            news_txt += f"\n[{r['name']}({sym}) 뉴스]\n"
            news_txt += "\n".join(f"  · ({h['date']}) {h['title']}" for h in heads) or "  · (뉴스 없음)"
            news_txt += "\n"

        price_rule = "- 미국 주식 시황 분석 시 본문에 인용하는 모든 주가 수치(달러)는 반드시 소수점 두 자리까지 정확히 표기할 것 (예: $125.43 또는 125.43달러)" if is_us else "- 한국 주식 분석 시 본문에 인용하는 주가는 소수점 없이 원화 정수로 표기할 것 (예: 72,500원)"

        sys_inst = f"""당신은 증권 시황 분석 전문 에디터입니다.
제공된 가격 데이터와 뉴스 헤드라인을 바탕으로 한국어 시황 분석 리포트를 작성하세요.
규칙:
- 본문에 쓰는 모든 가격 수치는 반드시 '종가(close)' 기준으로 작성 (장중가·시가 사용 금지)
- 종목명은 반드시 제공된 한글 종목명으로 표기 (종목 코드 단독 표기 금지)
- 반드시 제공된 수치(시작종가, 현재 종가, 등락률 등)를 인용해 근거를 제시
{price_rule}
- 뉴스 헤드라인과 가격 흐름을 연결해 해석
- 과장·투자 권유 금지, 객관적 사실 기반
- 마크다운/코드블록 없이 일반 문단 텍스트로만 출력
- 종목 종합 요약 → 종목별 코멘트 → 유의점 순서, 800~1200자"""

        user = (
            f"시장: {market}, 분석 기간: {period_label}, 뉴스 시간대 필터: {news_filter}\n\n"
            f"[가격 데이터]\n{price_txt}\n\n"
            f"[뉴스 헤드라인]\n{news_txt}\n\n"
            "위 데이터를 바탕으로 시황 분석 리포트를 작성해 주세요."
        )
        resp = client.models.generate_content(
            model=model_id,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=sys_inst, temperature=0.6,
            ),
        )
        return (resp.text or "(분석 생성 실패)").strip()

    # ──────────────────────────────────────────────
    # HTML 출력
    # ──────────────────────────────────────────────
    def _write_html(self, path, price_rows, news_map, analysis,
                    line_png, bar_png, index_data, period_label, market, now, news_filter) -> None:
        esc = html.escape

        is_active = self._is_market_active(market)
        title_prefix = "실시간 시세" if is_active else "당일 시세"

        last_dt_label = price_rows[0]["last_dt"] if price_rows else ""
        if last_dt_label and not is_active:
            tz_suffix = " (ET)" if market == "🇺🇸 미국" else " (KST)"
            if tz_suffix not in last_dt_label:
                last_dt_label += tz_suffix

        time_suffix = f": {last_dt_label}" if last_dt_label else ""
        title_suffix = f"실시간 기준{time_suffix}" if is_active else f"장마감 기준{time_suffix}"
        market_label = 'NYSE' if market == '🇺🇸 미국' else 'KRX'

        market_summary_name = "미국 증시 요약" if market == "🇺🇸 미국" else "한국 증시 요약"

        def color(v):
            return "#E63B2E" if v >= 0 else "#0055FF"

        # 가격 포맷: 미국 소수점 2자리, 한국 정수
        _us = (market == "🇺🇸 미국")
        def pfmt(v): return f"{v:,.2f}" if _us else f"{v:,.0f}"

        def capfmt(v: int) -> str:
            if v <= 0: return "-"
            if _us:
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                return f"${v/1e6:.0f}M"
            else:
                if v >= 1e12: return f"{v/1e12:.1f}조"
                if v >= 1e8:  return f"{v/1e8:.0f}억"
                return f"{v:,}"

        # 당일 시세 표 (전체 종목 한 테이블)
        quote_trs = ""
        for r in price_rows:
            base   = re.sub(r"\.[A-Z]+$", "", r["symbol"])
            up     = r["diff"] >= 0
            arrow  = "▲" if up else "▼"
            c      = color(r["day_chg"])
            tv_mil = r["trade_value"] / 1e6
            quote_trs += (
                "<tr>"
                f"<td><b>{esc(r['name'])}</b><br><span class='sym'>{esc(base)}</span></td>"
                f"<td class='num'>{capfmt(r['mktcap'])}</td>"
                f"<td class='num'>{pfmt(r['prev_close'])}</td>"
                f"<td class='num' style='color:{c}'>{pfmt(r['last'])}<br>"
                f"<span style='font-size:12px'>{arrow} {pfmt(abs(r['diff']))} ({r['day_chg']:+.2f}%)</span></td>"
                f"<td class='num'>{r['volume']:,}</td>"
                f"<td class='num'>{pfmt(tv_mil)} 백만</td>"
                "</tr>"
            )
        quote_cards = (
            "<table>"
            "<tr><th>종목</th><th>시총</th><th>전일</th><th>종가</th><th>거래량</th><th>거래대금</th></tr>"
            f"{quote_trs}"
            "</table>"
        )

        # 시장 지수 박스 (코스피·코스닥·코스피200)
        idx_boxes_html = ""
        if index_data:
            boxes = ""
            for i, idx in enumerate(index_data[:3]):
                is_dark = (i == 0)
                bg  = "#1A1A1A" if is_dark else "#FFFFFF"
                nc  = "#AAAAAA" if is_dark else "#666666"
                up  = idx["diff"] >= 0
                vc  = ("#FF5555" if up else "#5599FF") if is_dark else ("#E63B2E" if up else "#0055FF")
                arrow = "▲" if up else "▼"
                boxes += (
                    f"<div style='flex:1; padding:14px 18px; background:{bg};"
                    f" border:2px solid #CCCCCC; border-radius:4px;'>"
                    f"<div style='font-size:12px; color:{nc}; margin-bottom:6px;'>{esc(idx['name'])}</div>"
                    f"<div style='font-size:22px; font-weight:bold; color:{vc};"
                    f" font-variant-numeric:tabular-nums;'>{idx['last']:,.2f}</div>"
                    f"<div style='font-size:12px; color:{vc}; margin-top:4px;'>"
                    f"{arrow} {abs(idx['diff']):,.2f} &nbsp; {idx['pct']:+.2f}%</div>"
                    f"</div>"
                )
            idx_boxes_html = f"<div style='display:flex; gap:8px; margin:12px 0;'>{boxes}</div>"

        def base_code(sym):
            return re.sub(r"\.[A-Z]+$", "", sym)

        # 장 최종 일시 (헤더 아래 표시용)
        # 이미 상단에서 정의됨

        # 가격 표
        price_trs = ""
        for r in price_rows:
            price_trs += (
                "<tr>"
                f"<td><b>{esc(r['name'])}</b><br><span class='sym'>{esc(base_code(r['symbol']))}</span></td>"
                f"<td class='num'>{pfmt(r['last'])}</td>"
                f"<td class='num' style='color:{color(r['day_chg'])}'>{r['day_chg']:+.2f}%</td>"
                f"<td class='num' style='color:{color(r['period_chg'])}'>{r['period_chg']:+.2f}%</td>"
                f"<td class='num'>{pfmt(r['high'])}</td>"
                f"<td class='num'>{pfmt(r['low'])}</td>"
                f"<td class='num'>{r['volume']:,}</td>"
                "</tr>"
            )

        # 뉴스 표
        news_trs = ""
        for r in price_rows:
            heads = news_map.get(r["symbol"], [])
            if not heads:
                news_trs += f"<tr><td><b>{esc(r['name'])}</b></td><td colspan='2'>(뉴스 없음)</td></tr>"
                continue
            for i, h in enumerate(heads):
                first = (
                    f"<td rowspan='{len(heads)}'><b>{esc(r['name'])}</b><br>"
                    f"<span class='sym'>{esc(base_code(r['symbol']))}</span></td>"
                    if i == 0 else ""
                )
                link = esc(h["link"])
                news_trs += (
                    "<tr>"
                    f"{first}"
                    f"<td class='date'>{esc(h['date'])}</td>"
                    f"<td><a href='{link}' target='_blank'>{esc(h['title'])}</a></td>"
                    "</tr>"
                )

        analysis_html = ""
        for p in analysis.split("\n"):
            p_clean = p.strip()
            if not p_clean:
                continue
            if p_clean.startswith('#'):
                p_clean = re.sub(r'^#+\s*', '', p_clean)
                p_clean = re.sub(r'[#\*\_]+', '', p_clean).strip()
                analysis_html += f"<h3>{html.escape(p_clean)}</h3>"
            else:
                p_html = html.escape(p_clean)
                p_html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', p_html)
                p_html = re.sub(r'\*(.*?)\*', r'<i>\1</i>', p_html)
                analysis_html += f"<p>{p_html}</p>"

        doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>주식 뉴스 리포트 {now.strftime('%Y-%m-%d')}</title>
<style>
  body {{ font-family:'맑은 고딕','Malgun Gothic',sans-serif; max-width:920px;
          margin:0 auto; padding:24px; color:#1A1A1A; background:#F5F0E8; }}
  h1 {{ border-bottom:4px solid #1A1A1A; padding-bottom:8px; }}
  h2 {{ background:#FFCC00; display:inline-block; padding:5px 14px;
        border:2px solid #1A1A1A; margin-top:32px; font-size:20px; font-weight:bold; }}
  h3 {{ font-size:16px; font-weight:bold; margin-top:16px; margin-bottom:6px; }}
  table {{ border-collapse:collapse; width:100%; background:#fff;
           border:3px solid #1A1A1A; margin:12px 0; }}
  th {{ background:#1A1A1A; color:#fff; padding:8px; font-size:14px; }}
  td {{ border:1px solid #ccc; padding:8px; font-size:13px; vertical-align:top; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.date {{ color:#4A4A4A; white-space:nowrap; }}
  .sym {{ color:#0055FF; font-size:11px; font-family:Consolas,monospace; }}
  img {{ width:100%; border:3px solid #1A1A1A; margin:12px 0; background:#fff; }}
  .meta {{ color:#4A4A4A; font-size:13px; }}
  a {{ color:#0055FF; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  p {{ line-height:1.7; }}
  .quote {{ background:#fff; border:3px solid #1A1A1A; margin:12px 0; padding:12px 16px; }}
  .qhead {{ font-size:15px; border-bottom:2px solid #1A1A1A; padding-bottom:6px; }}
  .qhead .qdate {{ float:right; color:#4A4A4A; font-size:12px; font-weight:normal; }}
  .qprice {{ font-size:30px; font-weight:bold; margin:8px 0;
             font-variant-numeric:tabular-nums; }}
  .qprice .qdiff {{ font-size:14px; margin-left:10px; }}
  .qtable {{ border:none; margin:0; width:100%; }}
  .qtable th {{ background:#F5F0E8; color:#1A1A1A; text-align:left;
                width:80px; font-size:13px; border:1px solid #ddd; }}
  .qtable td {{ border:1px solid #ddd; }}
</style></head><body>
<h1>📈 주식 / ETF 뉴스 리포트</h1>
<p class="meta">시장: {esc(market)} &nbsp;|&nbsp; 분석 기간: {esc(period_label)} &nbsp;|&nbsp; 뉴스 필터: {esc(news_filter)}
&nbsp;|&nbsp; 작성: {now.strftime('%Y-%m-%d %H:%M')} (KST)</p>

<h2>① {title_prefix} <span style="font-size:13px;font-weight:normal;">({market_label} {title_suffix})</span></h2>
{idx_boxes_html}
{quote_cards}

<h2>② {market_summary_name} &nbsp;|&nbsp; 분석 기간: {esc(period_label)}</h2>
<p style="font-size:14px; font-weight:bold; color:#1A1A1A; margin:6px 0 10px 0;">장 최종 일시: {esc(last_dt_label)}</p>
<table>
<tr><th>종목</th><th>현재 종가</th><th>일간</th><th>기간등락</th><th>기간고가</th><th>기간저가</th><th>거래량</th></tr>
{price_trs}
</table>

<h2>③ 추이 그래프</h2>
<img src="charts/{line_png.name}" alt="가격 추이">
<img src="charts/{bar_png.name}" alt="기간 등락률">

<h2>④ 종목별 뉴스</h2>
<table>
<tr><th>종목</th><th>날짜</th><th>헤드라인</th></tr>
{news_trs}
</table>

<h2>⑤ 종합 분석</h2>
{analysis_html}

<p class="meta" style="margin-top:32px;">
※ 데이터 출처: Yahoo Finance(yfinance), 구글 뉴스 RSS.
본 리포트는 정보 제공용이며 투자 권유가 아닙니다.</p>
</body></html>"""

        path.write_text(doc, encoding="utf-8")
