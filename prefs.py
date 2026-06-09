# pyright: reportMissingImports=false
"""
prefs.py — 주식 리포트 분석 변수 체크 상태 영속화 (평문 JSON)
config.json(DPAPI 암호화)과 분리된 비민감 설정 저장소.
"""
import json
import os

try:
    from standalone_poster import _app_dir
except Exception:
    def _app_dir():
        base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                or os.path.expanduser("~"))
        path = os.path.join(base, "NaverBlogAutoPoster")
        os.makedirs(path, exist_ok=True)
        return path

PREFS_FILE = "stock_report_prefs.json"


def _prefs_path() -> str:
    return os.path.join(_app_dir(), PREFS_FILE)


def load_prefs() -> dict:
    """저장된 체크 상태 dict 반환. 없으면 빈 dict."""
    path = _prefs_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def save_prefs(prefs: dict) -> None:
    """체크 상태 dict 를 JSON 으로 저장."""
    try:
        with open(_prefs_path(), "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[경고] 변수 선택 저장 실패: {e}")
