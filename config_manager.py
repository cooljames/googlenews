# pyright: reportMissingImports=false
"""
config_manager.py — 설정 파일 관리 및 DPAPI 자격증명 암호화/복호화 모듈
"""
import os
import json
import base64
import ctypes
from ctypes import wintypes

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_encrypt(text: str) -> str:
    if not text:
        return ""
    try:
        if os.name != "nt":
            return text
        data_bytes = text.encode("utf-8")
        in_blob = DATA_BLOB(len(data_bytes), ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            enc_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return base64.b64encode(enc_bytes).decode("utf-8")
    except Exception:
        pass
    return text

def dpapi_decrypt(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        if os.name != "nt":
            return cipher_text
        enc_bytes = base64.b64decode(cipher_text.encode("utf-8"), validate=True)
        in_blob = DATA_BLOB(len(enc_bytes), ctypes.cast(ctypes.create_string_buffer(enc_bytes), ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            dec_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return dec_bytes.decode("utf-8")
    except Exception:
        pass
    return cipher_text

def _app_dir():
    app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(app_data, "NaverBlogAutoPoster")
    os.makedirs(path, exist_ok=True)
    return path

def _config_path():
    return os.path.join(_app_dir(), "config.json")

def load_config():
    path = _config_path()
    cfg = {
        "gemini_api_key": "",
        "naver_id":       "",
        "naver_pw":       "",
        "gemini_model":   "",
    }
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            cfg["gemini_api_key"] = dpapi_decrypt(loaded.get("gemini_api_key", ""))
            cfg["naver_id"]       = dpapi_decrypt(loaded.get("naver_id", ""))
            cfg["naver_pw"]       = dpapi_decrypt(loaded.get("naver_pw", ""))
            cfg["gemini_model"]   = loaded.get("gemini_model", "")
        except Exception:
            pass
    return cfg

def save_config(cfg):
    existing_cfg = {}
    path = _config_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing_cfg = json.load(f)
        except Exception:
            pass
    existing_cfg["gemini_api_key"] = dpapi_encrypt(cfg.get("gemini_api_key", existing_cfg.get("gemini_api_key", "")))
    existing_cfg["naver_id"]       = dpapi_encrypt(cfg.get("naver_id", existing_cfg.get("naver_id", "")))
    existing_cfg["naver_pw"]       = dpapi_encrypt(cfg.get("naver_pw", existing_cfg.get("naver_pw", "")))
    existing_cfg["gemini_model"]   = cfg.get("gemini_model", existing_cfg.get("gemini_model", ""))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing_cfg, f, ensure_ascii=False, indent=2)

def migrate_config():
    path = _config_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        return
    migrated = False
    gemini_key = loaded.get("gemini_api_key", "")
    if gemini_key:
        decrypted_gemini = dpapi_decrypt(gemini_key)
        if decrypted_gemini == gemini_key and not gemini_key.startswith("AQAAAN"):
            loaded["gemini_api_key"] = dpapi_encrypt(gemini_key)
            migrated = True
    naver_id = loaded.get("naver_id", "")
    if naver_id:
        decrypted_id = dpapi_decrypt(naver_id)
        if decrypted_id == naver_id and not naver_id.startswith("AQAAAN"):
            loaded["naver_id"] = dpapi_encrypt(naver_id)
            migrated = True
    naver_pw = loaded.get("naver_pw", "")
    if naver_pw:
        decrypted_pw = dpapi_decrypt(naver_pw)
        if decrypted_pw == naver_pw and not naver_pw.startswith("AQAAAN"):
            loaded["naver_pw"] = dpapi_encrypt(naver_pw)
            migrated = True
    if migrated:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(loaded, f, ensure_ascii=False, indent=2)
            print("🔒 평문으로 저장되어 있던 Google API Key, 네이버 ID 또는 네이버 비밀번호를 안전하게 암호화하여 다시 저장했습니다.")
        except Exception:
            pass
