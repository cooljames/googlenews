# pyright: reportMissingImports=false
"""
market_data.py — 한·미 거시 분석 변수 레지스트리 + 수집 엔진

- VAR_REGISTRY: 시장(kr/us) → 카테고리 → 변수 목록.
  각 변수: key, label, source, spec, status, fmt
    · source "yf"      : 단일 yfinance 심볼(spec=심볼 문자열)
    · source "yf_multi": 여러 심볼 묶음(spec=[(소제목, 심볼), ...])
    · source "derived" : 합성 지표(예: CNY/KRW = KRW=X ÷ CNY=X)
    · source "na"      : 무료 안정 소스 없음 → status="soon"(준비중, 비활성)
  status "ok" 만 실제 수집. "soon" 은 UI에서 비활성 표시.
- collect_selected(selected): 체크된 ok 변수만 수집해 카테고리별 정규화 결과 반환.
- kr_status()/us_status(): 현재 KST 기준 장 상태 판별.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta, time as dtime, date

import yfinance as yf

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────────────────────
# 변수 레지스트리
# ──────────────────────────────────────────────────────────────
def _v(key, label, source, spec, status="ok", fmt="price"):
    return {"key": key, "label": label, "source": source,
            "spec": spec, "status": status, "fmt": fmt}


def _na(key, label):
    return _v(key, label, "na", None, status="soon")


VAR_REGISTRY = {
    "kr": [
        {"cat": "indices", "title": "① 국내 핵심 지수", "vars": [
            _v("kospi",    "KOSPI",    "yf", "^KS11"),
            _v("kosdaq",   "KOSDAQ",   "yf", "^KQ11"),
            _v("kospi200", "KOSPI200", "yf", "^KS200"),
            _na("krx300",       "KRX 300"),
            _na("kospi_large",  "KOSPI 대형주"),
            _na("kospi_mid",    "중형주"),
            _na("kospi_small",  "소형주"),
        ]},
        {"cat": "investors", "title": "투자자별 수급 (순매수/순매도)", "vars": [
            _na("foreign",     "외국인"),
            _na("institution", "기관"),
            _na("individual",  "개인"),
            _na("pension",     "연기금"),
            _na("program",     "프로그램 매매(차익/비차익)"),
        ]},
        {"cat": "internals", "title": "시장 내부 변수", "vars": [
            _na("trade_value",    "거래대금"),
            _na("trade_volume",   "거래량"),
            _na("credit_balance", "신용잔고"),
            _na("short_balance",  "공매도 잔고"),
            _na("adr",            "등락비율(ADR)"),
            _na("updown",         "상승/하락 종목 수"),
            _na("vkospi",         "VKOSPI(변동성지수)"),
        ]},
        {"cat": "rates", "title": "금리 / 채권", "vars": [
            _na("ktb3",        "국고채 3년"),
            _na("ktb10",       "국고채 10년"),
            _na("cd",          "CD금리"),
            _na("corp_spread", "회사채 스프레드(AA-)"),
        ]},
        {"cat": "fx", "title": "② 환율", "vars": [
            _v("usdkrw", "USD/KRW(원/달러)", "yf",      "KRW=X"),
            _v("jpykrw", "JPY/KRW(엔/원)",   "yf",      "JPYKRW=X"),
            _v("cnykrw", "CNY/KRW(위안/원)", "derived", "cnykrw"),
        ]},
        {"cat": "overseas", "title": "③ 해외 참조 변수 (한국장에 직접 영향)", "vars": [
            _v("us3_prev", "미국 3대 지수 전일 마감(다우·S&P500·나스닥)", "yf_multi",
               [("다우", "^DJI"), ("S&P500", "^GSPC"), ("나스닥", "^IXIC")]),
            _v("us_futures", "미국 지수 선물(실시간)", "yf_multi",
               [("다우선물", "YM=F"), ("S&P선물", "ES=F"), ("나스닥선물", "NQ=F")]),
            _v("sox",      "필라델피아 반도체지수(SOX)", "yf", "^SOX"),
            _v("dxy",      "달러인덱스(DXY)",           "yf", "DX-Y.NYB"),
            _v("vix",      "VIX(미국 변동성)",          "yf", "^VIX"),
            _v("us10y",    "미국채 10년물 금리",        "yf", "^TNX", fmt="pct"),
            _v("shanghai", "중국 상하이종합",           "yf", "000001.SS"),
            _v("nikkei",   "일본 닛케이225",            "yf", "^N225"),
            _v("hangseng", "홍콩 항셍",                 "yf", "^HSI"),
            _v("wti",      "WTI 유가",                  "yf", "CL=F"),
            _v("gold",     "금 가격",                   "yf", "GC=F"),
        ]},
    ],
    "us": [
        {"cat": "indices", "title": "① 주요 지수 (3~4대 지수)", "vars": [
            _v("djia",        "다우존스 산업평균(DJIA)",        "yf", "^DJI"),
            _v("sp500",       "S&P 500",                        "yf", "^GSPC"),
            _v("nasdaq",      "나스닥 종합",                    "yf", "^IXIC"),
            _v("nasdaq100",   "나스닥 100",                     "yf", "^NDX"),
            _v("russell2000", "러셀 2000(Russell 2000)",        "yf", "^RUT"),
            _v("sox",         "필라델피아 반도체지수(SOX)",     "yf", "^SOX"),
        ]},
        {"cat": "volatility", "title": "② 변동성 / 심리 지표", "vars": [
            _v("vix", "VIX(공포지수)", "yf", "^VIX"),
            _na("putcall",   "Put/Call Ratio"),
            _na("feargreed", "Fear & Greed Index"),
            _na("aaii",      "AAII 투자심리"),
        ]},
        {"cat": "rates", "title": "③ 금리 / 채권 (외적 참조)", "vars": [
            _na("fedfunds",    "연방기금금리(Fed Funds)"),
            _na("us2y",        "미국채 2년물"),
            _v("us10y", "미국채 10년물", "yf", "^TNX", fmt="pct"),
            _v("us30y", "미국채 30년물", "yf", "^TYX", fmt="pct"),
            _na("yieldspread", "장단기 금리차(10년-2년)"),
        ]},
        {"cat": "currency", "title": "④ 통화", "vars": [
            _v("dxy",    "달러인덱스(DXY)", "yf", "DX-Y.NYB"),
            _v("eurusd", "EUR/USD",         "yf", "EURUSD=X"),
            _v("usdjpy", "USD/JPY",         "yf", "JPY=X"),
            _v("usdcny", "USD/CNY",         "yf", "CNY=X"),
        ]},
        {"cat": "commodities", "title": "⑤ 원자재", "vars": [
            _v("wti",    "WTI 원유",  "yf", "CL=F"),
            _v("brent",  "브렌트유",  "yf", "BZ=F"),
            _v("gold",   "금",        "yf", "GC=F"),
            _v("silver", "은",        "yf", "SI=F"),
            _v("copper", "구리",      "yf", "HG=F"),
            _v("natgas", "천연가스",  "yf", "NG=F"),
        ]},
        {"cat": "crypto", "title": "⑥ 암호화폐 (위험자산 심리 참조)", "vars": [
            _v("btc", "비트코인(BTC)",  "yf", "BTC-USD"),
            _v("eth", "이더리움(ETH)",  "yf", "ETH-USD"),
        ]},
        {"cat": "sectors", "title": "⑦ 섹터 ETF (GICS 11섹터)", "vars": [
            _v("xlk",  "XLK(기술)",        "yf", "XLK"),
            _v("xlf",  "XLF(금융)",        "yf", "XLF"),
            _v("xle",  "XLE(에너지)",      "yf", "XLE"),
            _v("xlv",  "XLV(헬스케어)",    "yf", "XLV"),
            _v("xly",  "XLY(임의소비)",    "yf", "XLY"),
            _v("xlp",  "XLP(필수소비)",    "yf", "XLP"),
            _v("xli",  "XLI(산업)",        "yf", "XLI"),
            _v("xlb",  "XLB(소재)",        "yf", "XLB"),
            _v("xlu",  "XLU(유틸리티)",    "yf", "XLU"),
            _v("xlre", "XLRE(부동산)",     "yf", "XLRE"),
            _v("xlc",  "XLC(커뮤니케이션)", "yf", "XLC"),
        ]},
        {"cat": "breadth", "title": "⑧ 시장 폭(Breadth)", "vars": [
            _na("new_highs", "신고가/신저가 종목 수"),
            _na("ma_ratio",  "50일/200일 이평선 상회 비율"),
            _na("nyse_adv",  "NYSE 상승/하락 거래량"),
        ]},
    ],
}


# ──────────────────────────────────────────────────────────────
# 장 상태 판별
# ──────────────────────────────────────────────────────────────
def _kst_to_et(dt_kst: datetime) -> datetime:
    """KST → 미국 동부시간(ET). 서머타임 근사 적용."""
    dt_utc = dt_kst.astimezone(timezone.utc)
    y, m, d = dt_utc.year, dt_utc.month, dt_utc.day
    is_dst = False
    if 4 <= m <= 10:
        is_dst = True
    elif m == 3:
        first_w = date(y, 3, 1).weekday()
        second_sun = 1 + (6 - first_w) % 7 + 7
        if d > second_sun or (d == second_sun and dt_utc.hour >= 7):
            is_dst = True
    elif m == 11:
        first_w = date(y, 11, 1).weekday()
        first_sun = 1 + (6 - first_w) % 7
        if d < first_sun or (d == first_sun and dt_utc.hour < 6):
            is_dst = True
    offset = timedelta(hours=-4) if is_dst else timedelta(hours=-5)
    return (dt_utc + offset).replace(tzinfo=None)


def get_latest_trading_date(market_type: str) -> date:
    """시장별 가장 최근 정규장 거래일 반환."""
    now_kst = datetime.now(KST)
    if market_type == "us":
        et = _kst_to_et(now_kst)
        w = et.weekday()
        t = et.time()
        # 주말 휴장
        if w == 5: # 토요일 -> 금요일
            return (et - timedelta(days=1)).date()
        elif w == 6: # 일요일 -> 금요일
            return (et - timedelta(days=2)).date()
        # 평일
        if t < dtime(9, 30):
            # 장전 -> 이전 영업일
            if w == 0: # 월요일 장전 -> 금요일
                return (et - timedelta(days=3)).date()
            else: # 화~금 장전 -> 어제
                return (et - timedelta(days=1)).date()
        else:
            return et.date()
    else: # "kr"
        w = now_kst.weekday()
        t = now_kst.time()
        # 주말 휴장
        if w == 5:
            return (now_kst - timedelta(days=1)).date()
        elif w == 6:
            return (now_kst - timedelta(days=2)).date()
        # 평일
        if t < dtime(9, 0):
            if w == 0:
                return (now_kst - timedelta(days=3)).date()
            else:
                return (now_kst - timedelta(days=1)).date()
        else:
            return now_kst.date()


def kr_status(now: datetime = None) -> tuple:
    """한국 시장 상태 → (라벨, 상세, 실시간여부)."""
    now = now or datetime.now(KST)
    if now.weekday() >= 5:
        return ("장마감", "주말 휴장", False)
    t = now.time()
    if dtime(9, 0) <= t <= dtime(15, 30):
        return ("정규장", f"{now:%H:%M} KST", True)
    if t < dtime(9, 0):
        return ("장전", "09:00 개장 예정", False)
    return ("장마감", "15:30 종료 · 전일 종가 기준", False)


def us_status(now: datetime = None) -> tuple:
    """미국 시장 상태 → (라벨, 상세, 실시간여부). KST 입력 기준."""
    now = now or datetime.now(KST)
    et = _kst_to_et(now)
    if et.weekday() >= 5:
        return ("장마감", "주말 휴장", False)
    t = et.time()
    if dtime(9, 30) <= t <= dtime(16, 0):
        return ("정규장", f"{et:%H:%M} ET", True)
    if dtime(4, 0) <= t < dtime(9, 30):
        return ("프리마켓", f"{et:%H:%M} ET", True)
    if dtime(16, 0) < t <= dtime(20, 0):
        return ("애프터마켓", f"{et:%H:%M} ET", True)
    return ("장마감", "정규장 종료 · 마감 데이터 기준", False)


# ──────────────────────────────────────────────────────────────
# yfinance 수집
# ──────────────────────────────────────────────────────────────
def _quote_from_close(close):
    if close is None or len(close) == 0:
        return None
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else last
    try:
        asof = close.index[-1].strftime("%Y-%m-%d")
    except Exception:
        asof = ""
    return {"last": last, "prev": prev, "diff": last - prev,
            "pct": (last - prev) / prev * 100 if prev else 0.0, "asof": asof}


def _fetch_naver_index(code: str) -> dict:
    url = f"https://m.stock.naver.com/api/index/{code}/basic"
    try:
        import urllib.request
        import json
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        last = float(data['closePrice'].replace(',', ''))
        diff = float(data['compareToPreviousClosePrice'].replace(',', ''))
        pct  = float(data['fluctuationsRatio'].replace(',', ''))

        # name 필드는 'FALLING'/'RISING'(영문) 또는 '하락'/'상승'(한글) 두 형태 모두 가능.
        # API가 이미 부호를 포함해 반환하지만, abs()로 정규화 후 name 기준으로 부호를 확정한다.
        sign_name = (data.get('compareToPreviousPrice', {}) or {}).get('name', '')
        is_falling = 'FALL' in sign_name or 'DOWN' in sign_name or '하락' in sign_name or '하한가' in sign_name
        diff = -abs(diff) if is_falling else abs(diff)
        pct  = -abs(pct)  if is_falling else abs(pct)
            
        asof = data.get('localTradedAt', '')[:10]
        return {"last": last, "prev": last - diff, "diff": diff, "pct": pct, "asof": asof}
    except Exception as e:
        print(f"  [경고] Naver 지수 {code} 수집 실패: {e}")
        return None

def is_symbol_market_active(sym: str) -> bool:
    """심볼별 거래 시간(장중) 여부 판별."""
    now_kst = datetime.now(KST)
    
    # 주말 여부 (토요일/일요일은 모든 일반 금융시장 휴장)
    if "-USD" in sym:  # 암호화폐는 24/7
        return True
        
    if now_kst.weekday() >= 5:
        return False
        
    # 1. 한국 시장 심볼
    if any(suffix in sym for suffix in [".KS", ".KQ", "^KS", "^KQ"]):
        return dtime(9, 0) <= now_kst.time() <= dtime(15, 30)
        
    # 2. 미국 주식/지수/ETF 심볼 (^DJI, ^GSPC, ^IXIC, ^NDX, ^RUT, ^SOX, XLK, XLF, XLE, etc.)
    # (선물 =F, FX =X 제외)
    is_us_stock_or_index = False
    if sym.startswith("^") and not sym.endswith("=F"):
        is_us_stock_or_index = True
    elif sym.split(".")[0].isalpha() and len(sym.split(".")[0]) <= 5 and not sym.endswith("=F") and not sym.endswith("=X"):
        is_us_stock_or_index = True
        
    if is_us_stock_or_index:
        et = _kst_to_et(now_kst)
        if et.weekday() >= 5:
            return False
        # 미국 정규장 시간: 09:30 ~ 16:00 ET
        return dtime(9, 30) <= et.time() <= dtime(16, 0)
        
    # 3. 아시아 다른 지수
    if sym == "^N225": # 일본
        t = now_kst.time()
        return (dtime(9, 0) <= t <= dtime(11, 30)) or (dtime(12, 30) <= t <= dtime(15, 0))
        
    if sym in ["000001.SS", "^HSI"]: # 중국/홍콩
        now_local = now_kst - timedelta(hours=1)
        if now_local.weekday() >= 5:
            return False
        t = now_local.time()
        if sym == "000001.SS":
            return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))
        else: # ^HSI
            return (dtime(9, 30) <= t <= dtime(12, 0)) or (dtime(13, 0) <= t <= dtime(16, 0))
            
    # 4. 선물(=F), FX(=X), 달러인덱스
    if sym.endswith("=F") or sym.endswith("=X") or "DX-Y" in sym:
        et = _kst_to_et(now_kst)
        w = et.weekday()
        t = et.time()
        if w == 5: # 토요일
            return False
        if w == 4 and t >= dtime(18, 0): # 금요일 18:00 ET 이후 휴장
            return False
        if w == 6 and t < dtime(17, 0): # 일요일 17:00 ET 이전 휴장
            return False
        return True
        
    return True

def fetch_yf_batch(symbols: list) -> dict:
    """심볼 리스트를 동시 조회 → {symbol: quote|None}."""
    symbols = list(dict.fromkeys(s for s in symbols if s))

    def work(sym):
        if sym == "^KS11":
            return sym, _fetch_naver_index("KOSPI")
        elif sym == "^KQ11":
            return sym, _fetch_naver_index("KOSDAQ")
        elif sym == "^KS200":
            return sym, _fetch_naver_index("KPI200")

        try:
            h = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            
            # fast_info 정보 수집 (장 상태 무관하게 항상 가져오기 시도)
            fast_price = None
            fast_prev = None
            try:
                tk = yf.Ticker(sym)
                fast = tk.fast_info
                if fast:
                    if getattr(fast, "last_price", None) is not None:
                        fast_price = float(fast.last_price)
                    if getattr(fast, "previous_close", None) is not None:
                        fast_prev = float(fast.previous_close)
            except Exception as fe:
                print(f"  [경고] {sym} fast_info 조회 실패: {fe}")

            import pandas as pd
            if h is not None and "Close" in h and not h.empty:
                last_idx = h.index[-1]
                if pd.isna(h["Close"].iloc[-1]) and fast_price is not None:
                    h.loc[last_idx, "Close"] = fast_price

            if h is not None and "Close" in h:
                close_series = h["Close"].dropna()
                quote = _quote_from_close(close_series)
            else:
                quote = None

            if quote and fast_price is not None:
                live_price = fast_price
                prev_close = fast_prev if fast_prev is not None else quote["prev"]
                quote["last"] = live_price
                quote["prev"] = prev_close
                quote["diff"] = live_price - prev_close
                quote["pct"] = (live_price - prev_close) / prev_close * 100 if prev_close else 0.0

                now_kst = datetime.now(KST)
                if any(us_key in sym for us_key in ["^DJI", "^GSPC", "^IXIC", "^NDX", "^RUT", "^SOX", "^VIX", "^TNX", "^TYX"]):
                    if is_symbol_market_active(sym):
                        et_now = _kst_to_et(now_kst)
                        quote["asof"] = et_now.strftime("%Y-%m-%d %H:%M") + " (ET)"
                    else:
                        ld = get_latest_trading_date("us")
                        quote["asof"] = f"{ld} 16:00 (ET)"
                else:
                    if is_symbol_market_active(sym):
                        quote["asof"] = now_kst.strftime("%Y-%m-%d %H:%M") + " (KST)"
                    else:
                        ld = get_latest_trading_date("kr")
                        quote["asof"] = f"{ld} 15:30 (KST)"

            return sym, quote
        except Exception as e:
            print(f"  [경고] {sym} 수집 실패: {e}")
        return sym, None

    out = {}
    if not symbols:
        return out
    with ThreadPoolExecutor(max_workers=10) as ex:
        for sym, q in ex.map(work, symbols):
            out[sym] = q
    return out


def _derive(key: str, batch: dict):
    """합성 지표 계산."""
    if key == "cnykrw":
        krw, cny = batch.get("KRW=X"), batch.get("CNY=X")
        if krw and cny and cny["last"]:
            last = krw["last"] / cny["last"]
            prev = (krw["prev"] / cny["prev"]) if cny["prev"] else last
            return {"last": last, "prev": prev, "diff": last - prev,
                    "pct": (last - prev) / prev * 100 if prev else 0.0,
                    "asof": krw.get("asof", "")}
    return None


# ──────────────────────────────────────────────────────────────
# 선택 변수 수집
# ──────────────────────────────────────────────────────────────
def _is_checked(selected: dict, market: str, cat: str, key: str) -> bool:
    return bool(selected.get(market, {}).get(cat, {}).get(key))


def selected_symbols(selected: dict) -> list:
    """체크된 ok 변수가 요구하는 yfinance 심볼 전체(합성 의존 포함)."""
    syms = []
    for market, cats in VAR_REGISTRY.items():
        for cat in cats:
            for v in cat["vars"]:
                if v["status"] != "ok":
                    continue
                if not _is_checked(selected, market, cat["cat"], v["key"]):
                    continue
                if v["source"] == "yf":
                    syms.append(v["spec"])
                elif v["source"] == "yf_multi":
                    syms += [s for _, s in v["spec"]]
                elif v["source"] == "derived" and v["spec"] == "cnykrw":
                    syms += ["KRW=X", "CNY=X"]
    return list(dict.fromkeys(syms))


def collect_selected(selected: dict) -> dict:
    """체크된 ok 변수를 수집 → {market: [{cat,title,rows:[...]}]}.
    rows 항목: {label, fmt, quote(dict|None)}.  quote None = 데이터 없음."""
    batch = fetch_yf_batch(selected_symbols(selected))
    result = {"kr": [], "us": []}
    for market, cats in VAR_REGISTRY.items():
        for cat in cats:
            rows = []
            for v in cat["vars"]:
                if v["status"] != "ok":
                    continue
                if not _is_checked(selected, market, cat["cat"], v["key"]):
                    continue
                if v["source"] == "yf":
                    rows.append({"label": v["label"], "fmt": v["fmt"],
                                 "quote": batch.get(v["spec"])})
                elif v["source"] == "yf_multi":
                    for sub, sym in v["spec"]:
                        rows.append({"label": sub, "fmt": v["fmt"],
                                     "quote": batch.get(sym), "group": v["label"]})
                elif v["source"] == "derived":
                    rows.append({"label": v["label"], "fmt": v["fmt"],
                                 "quote": _derive(v["spec"], batch)})
            if rows:
                result[market].append({"cat": cat["cat"], "title": cat["title"],
                                       "rows": rows})
    return result


def has_selection(selected: dict) -> bool:
    """ok 변수가 하나라도 체크되었는지."""
    return len(selected_symbols(selected)) > 0
