# pyright: reportMissingImports=false
"""
standalone_poster.py — 외부 모듈 의존성 없이 단독 실행 가능한 스마트에디터 ONE 자동 포스팅 스크립트.

사용법:
    python standalone_poster.py --id <네이버ID> --pw <비밀번호> --title <제목> --content <본문>
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
import re
import time
import pyperclip
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
            cfg["gemini_model"]   = loaded.get("gemini_model", "")  # 평문 저장
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

def masked_input(prompt=""):
    """입력 글자를 * 로 표시하는 비밀번호 입력 함수 (Windows 전용)"""
    print(prompt, end="", flush=True)
    chars = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            print()
            break
        if ch == "\x08":  # 백스페이스
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
        elif ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        else:
            chars.append(ch)
            print("*", end="", flush=True)
    return "".join(chars)

def _cookie_path(naver_id):
    return os.path.join(_app_dir(), f"cookies_{naver_id}.json")

def save_cookies(driver, naver_id):
    try:
        with open(_cookie_path(naver_id), "w", encoding="utf-8") as f:
            json.dump(driver.get_cookies(), f, ensure_ascii=False)
        print("[쿠키] 세션 쿠키를 저장했습니다.")
    except Exception as e:
        print(f"[쿠키 저장 실패] {e}")

def load_cookies(driver, naver_id):
    path = _cookie_path(naver_id)
    if not os.path.exists(path):
        return False
    try:
        driver.get("https://naver.com")
        time.sleep(1)
        with open(path, encoding="utf-8") as f:
            cookies = json.load(f)
        for cookie in cookies:
            if "expiry" in cookie:
                cookie["expiry"] = int(cookie["expiry"])
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        print("[쿠키] 저장된 세션 쿠키를 복원했습니다.")
        return True
    except Exception as e:
        print(f"[쿠키 로드 실패] {e}")
        return False

def get_driver(naver_id, chrome_profile_path=None):
    # 계정별 크롬 프로필 경로 — ID가 다르면 세션이 분리됨
    if chrome_profile_path is None:
        chrome_profile_path = os.path.join(_app_dir(), f"chrome_profile_{naver_id}")
    chrome_profile_path = os.path.abspath(chrome_profile_path)

    # SingletonLock 락 파일 정리 (중복 실행 크래시 방지)
    lock_files = [
        os.path.join(chrome_profile_path, "SingletonLock"),
        os.path.join(chrome_profile_path, "Default", "SingletonLock"),
        os.path.join(chrome_profile_path, "lock"),
    ]
    for lock_file in lock_files:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

    # undetected_chromedriver: ChromeDriver 바이너리를 자동 패치하여 봇 감지 우회
    options = uc.ChromeOptions()
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, user_data_dir=chrome_profile_path, headless=False, version_main=148)
    try:
        driver.maximize_window()
    except Exception:
        pass

    # 언어·플러그인 핑거프린트 추가 은닉 (uc가 webdriver 속성은 이미 처리)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['ko-KR', 'ko', 'en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            """
        }
    )
    return driver

def _prepare_html_for_clipboard(html_text: str) -> str:
    """전체 HTML 문서에서 클립보드 프래그먼트용 콘텐츠를 추출하고,
    네이버 에디터 호환을 위해 테이블·단락 등 주요 인라인 스타일을 보강합니다."""
    import re

    # 1. <style> 블록에서 CSS 규칙 추출 (인라인 보강 참고용)
    style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html_text,
                              flags=re.DOTALL | re.IGNORECASE)
    # 합쳐서 키-값 파싱 (간이)
    css_text = '\n'.join(style_blocks)

    def _css_value(selector: str, prop: str) -> str:
        """css_text 에서 selector { ... prop: VALUE; } 추출."""
        pat = re.compile(
            re.escape(selector) + r'\s*\{([^}]*)\}', re.IGNORECASE)
        m = pat.search(css_text)
        if not m:
            return ''
        block = m.group(1)
        pm = re.search(re.escape(prop) + r'\s*:\s*([^;]+)', block, re.IGNORECASE)
        return pm.group(1).strip() if pm else ''

    # 2. <body> 내부 콘텐츠만 추출 (중첩 html/head/body 방지)
    body_match = re.search(r'<body[^>]*>(.*)</body>',
                           html_text, flags=re.DOTALL | re.IGNORECASE)
    if body_match:
        content = body_match.group(1).strip()
    else:
        # body 태그가 없으면 문서 껍데기만 제거
        content = html_text
        content = re.sub(r'<!DOCTYPE[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'</?html[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<head[^>]*>.*?</head>', '', content,
                         flags=re.DOTALL | re.IGNORECASE)
        content = content.strip()

    # 3. <style> 블록 자체를 본문에서 제거 (이미 인라인으로 적용할 것)
    content = re.sub(r'<style[^>]*>.*?</style>', '', content,
                     flags=re.DOTALL | re.IGNORECASE)

    # 4. <table> 인라인 스타일 보강 (border-collapse + border)
    table_style = (
        'border-collapse:collapse; width:100%; '
        'border:3px solid #1A1A1A; margin:12px 0; background:#fff;'
    )
    def _ensure_table(m):
        tag = m.group(0)
        if 'style=' in tag.lower():
            # 기존 style이 있지만 border가 없으면 추가
            if 'border' not in tag.lower():
                return re.sub(r"style=[\"']", lambda s: s.group(0) + table_style + ' ',
                              tag, count=1, flags=re.IGNORECASE)
            return tag
        return tag[:-1] + f' style="{table_style}">'
    content = re.sub(r'<table[^>]*>', _ensure_table, content, flags=re.IGNORECASE)

    # 5. <th> 인라인 스타일 보강
    th_style = 'background:#1A1A1A; color:#fff; padding:8px; font-size:14px; border:1px solid #ccc;'
    def _ensure_th(m):
        tag = m.group(0)
        if 'style=' in tag.lower():
            if 'border' not in tag.lower():
                return re.sub(r"style=[\"']", lambda s: s.group(0) + th_style + ' ',
                              tag, count=1, flags=re.IGNORECASE)
            return tag
        return tag[:-1] + f' style="{th_style}">'
    content = re.sub(r'<th[^>]*>', _ensure_th, content, flags=re.IGNORECASE)

    # 6. <td> 인라인 스타일 보강
    td_base = 'border:1px solid #ccc; padding:8px; font-size:13px; vertical-align:top;'
    def _ensure_td(m):
        tag = m.group(0)
        if 'style=' in tag.lower():
            # 이미 style이 있으면 border만 보강
            if 'border' not in tag.lower():
                return re.sub(r"style=[\"']", lambda s: s.group(0) + 'border:1px solid #ccc; ',
                              tag, count=1, flags=re.IGNORECASE)
            return tag
        return tag[:-1] + f' style="{td_base}">'
    content = re.sub(r'<td[^>]*>', _ensure_td, content, flags=re.IGNORECASE)

    # 7. <p> 인라인 스타일 보강 (단락 여백 + 줄간격 유지)
    def _ensure_p(m):
        tag = m.group(0)
        if 'style=' in tag.lower():
            extra = ''
            if 'line-height' not in tag.lower():
                extra += 'line-height:1.7; '
            if 'margin' not in tag.lower():
                extra += 'margin:10px 0; '
            if extra:
                return re.sub(r"style=[\"']", lambda s: s.group(0) + extra,
                              tag, count=1, flags=re.IGNORECASE)
            return tag
        return tag[:-1] + ' style="line-height:1.7; margin:10px 0;">'
    content = re.sub(r'<p[^>]*>', _ensure_p, content, flags=re.IGNORECASE)

    # 8. <h2> 인라인 스타일 보강 (섹션 제목, 밑줄 방지)
    h2_style = (
        'background:#FFCC00; display:inline-block; padding:5px 14px; '
        'border:2px solid #1A1A1A; margin-top:32px; font-size:20px; font-weight:bold; '
        'text-decoration:none; border-bottom:none;'
    )
    def _ensure_h2(m):
        tag = m.group(0)
        if 'style=' not in tag.lower():
            return tag[:-1] + f' style="{h2_style}">'
        if 'text-decoration' not in tag.lower():
            return re.sub(r"style=[\"']", lambda s: s.group(0) + 'text-decoration:none; border-bottom:none; ',
                          tag, count=1, flags=re.IGNORECASE)
        return tag
    content = re.sub(r'<h2[^>]*>', _ensure_h2, content, flags=re.IGNORECASE)

    # 9. <h3> 인라인 스타일 보강 (소제목, 밑줄 방지)
    h3_style = (
        'font-size:16px; font-weight:bold; margin-top:16px; margin-bottom:6px; '
        'text-decoration:none; border-bottom:none;'
    )
    def _ensure_h3(m):
        tag = m.group(0)
        if 'style=' not in tag.lower():
            return tag[:-1] + f' style="{h3_style}">'
        if 'text-decoration' not in tag.lower():
            return re.sub(r"style=[\"']", lambda s: s.group(0) + 'text-decoration:none; border-bottom:none; ',
                          tag, count=1, flags=re.IGNORECASE)
        return tag
    content = re.sub(r'<h3[^>]*>', _ensure_h3, content, flags=re.IGNORECASE)

    return content


def copy_html_and_text_to_clipboard(plain_text: str, html_text: str) -> bool:
    """Windows 클립보드에 평문(CF_UNICODETEXT)과 HTML 포맷(HTML Format)을 동시에 등록."""
    import ctypes
    from ctypes import wintypes
    
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    if not user32.OpenClipboard(None):
        return False
        
    try:
        user32.EmptyClipboard()
        
        # 1. 평문 등록 (CF_UNICODETEXT = 13)
        if plain_text:
            text_bytes = plain_text.encode('utf-16le')
            GMEM_MOVEABLE = 0x0002
            h_text_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes) + 2)
            if h_text_mem:
                p_text_mem = kernel32.GlobalLock(h_text_mem)
                if p_text_mem:
                    ctypes.memmove(p_text_mem, text_bytes, len(text_bytes))
                    ctypes.memset(p_text_mem + len(text_bytes), 0, 2)
                    kernel32.GlobalUnlock(h_text_mem)
                    user32.SetClipboardData(13, h_text_mem)
                    
        # 2. HTML 등록 (전처리 후 프래그먼트로 삽입)
        if html_text:
            # 전체 HTML 문서 → body 추출 + 인라인 스타일 보강
            fragment_content = _prepare_html_for_clipboard(html_text)

            header = (
                "Version:0.9\r\n"
                "StartHTML:{start_html:08d}\r\n"
                "EndHTML:{end_html:08d}\r\n"
                "StartFragment:{start_fragment:08d}\r\n"
                "EndFragment:{end_fragment:08d}\r\n"
            )
            dummy = header.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0)
            dummy_len = len(dummy.encode('utf-8'))
            
            fragment_start_tag = "<!--StartFragment-->"
            fragment_end_tag = "<!--EndFragment-->"
            
            html_doc = (
                "<html>\r\n"
                "<body>\r\n"
                f"{fragment_start_tag}{fragment_content}{fragment_end_tag}\r\n"
                "</body>\r\n"
                "</html>"
            )
            
            start_html = dummy_len
            start_fragment = start_html + len("<html>\r\n<body>\r\n".encode('utf-8')) + len(fragment_start_tag.encode('utf-8'))
            end_fragment = start_fragment + len(fragment_content.encode('utf-8'))
            end_html = end_fragment + len(fragment_end_tag.encode('utf-8')) + len("\r\n</body>\r\n</html>".encode('utf-8'))
            
            final_payload = header.format(
                start_html=start_html,
                end_html=end_html,
                start_fragment=start_fragment,
                end_fragment=end_fragment
            ) + html_doc
            
            payload_bytes = final_payload.encode('utf-8')
            
            CF_HTML = user32.RegisterClipboardFormatW("HTML Format")
            if CF_HTML:
                h_html_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload_bytes) + 1)
                if h_html_mem:
                    p_html_mem = kernel32.GlobalLock(h_html_mem)
                    if p_html_mem:
                        ctypes.memmove(p_html_mem, payload_bytes, len(payload_bytes))
                        ctypes.memset(p_html_mem + len(payload_bytes), 0, 1)
                        kernel32.GlobalUnlock(h_html_mem)
                        user32.SetClipboardData(CF_HTML, h_html_mem)
        return True
    except Exception as e:
        print(f"[클립보드] 리치 텍스트 복사 실패: {e}")
        return False
    finally:
        user32.CloseClipboard()

def clipboard_paste(driver, element, text, force_plain=False):
    """클립보드를 통한 복사 붙여넣기로 캡차(CAPTCHA) 방지"""
    import re
    
    is_html = False
    if not force_plain:
        is_html = bool(re.search(r'<(?:html|body|div|table|p|h[1-6]|ul|ol|br\s*/?)[\s>]', text, re.IGNORECASE))
        
    copied = False
    if is_html and os.name == "nt":
        # HTML 태그 제거하여 평문(fallback) 추출
        plain_text = re.sub(r"<[^>]+>", "", text)
        copied = copy_html_and_text_to_clipboard(plain_text, text)
        
    if not copied:
        pyperclip.copy(text)
        
    try:
        element.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
        except Exception:
            pass
        try:
            driver.execute_script("arguments[0].focus();", element)
        except Exception:
            pass
    time.sleep(0.3)
    actions = ActionChains(driver)
    actions.key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
    time.sleep(0.5)

def naver_login(driver, uid, upw):
    if not uid or not upw:
        print("[로그인] ID 또는 비밀번호가 누락되어 자동 로그인을 생략하고 수동 로그인을 대기합니다.")
        return False

    print(f"🔑 네이버 ID '{uid}'로 자동 로그인을 시도합니다...")
    driver.get("https://nid.naver.com/nidlogin.login")
    time.sleep(1.5)
    
    wait = WebDriverWait(driver, 10)
    try:
        # ID/PW 복사 붙여넣기로 캡차 방지
        id_input = wait.until(EC.presence_of_element_located((By.ID, "id")))
        clipboard_paste(driver, id_input, uid)
        time.sleep(0.5)
        
        pw_input = wait.until(EC.presence_of_element_located((By.ID, "pw")))
        clipboard_paste(driver, pw_input, upw)
        time.sleep(0.5)
        
        # 로그인 상태 유지 체크박스 클릭
        try:
            driver.find_element(By.CSS_SELECTOR, ".label_keep").click()
        except Exception:
            pass
            
        time.sleep(0.5)
        login_btn = wait.until(EC.element_to_be_clickable((By.ID, "log.login")))
        login_btn.click()
        time.sleep(3)
        
        # 기기 등록 화면 감지 및 우회 등록 처리
        try:
            new_save_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.ID, "new.save"))
            )
            print("[로그인] 기기 등록 창이 표시되어 '등록' 버튼을 자동 클릭합니다.")
            new_save_btn.click()
            time.sleep(2)
        except Exception:
            pass

        if "nidlogin.login" in driver.current_url:
            print("⚠️ 자동입력방지문자(CAPTCHA)가 작동했거나 로그인 정보가 맞지 않습니다.")
            return False

        print("✅ 자동 로그인 성공")
        save_cookies(driver, uid)
        return True
    except Exception as e:
        print(f"❌ 자동 로그인 시도 중 에러 발생: {e}")
        return False

def ensure_logged_in(driver, uid, upw):
    """로그인 상태 확인 및 필요시 로그인 진행"""
    print("[상태 체크] 네이버 로그인 세션 유효성을 확인합니다...")

    # 1. 저장된 쿠키 복원 시도 (크롬 프로필 세션이 만료된 경우 백업)
    load_cookies(driver, uid)

    driver.get(f"https://blog.naver.com/{uid}?Redirect=Write")
    time.sleep(2)

    current_url = driver.current_url
    if "nidlogin.login" in current_url or "nid.naver.com" in current_url:
        print("[상태 체크] 로그인이 필요합니다. 로그인 프로세스를 개시합니다.")
        success = naver_login(driver, uid, upw)

        # 자동 로그인 실패 시 캡차 발생 → 사용자가 직접 로그인할 수 있게 120초 대기
        if not success:
            timeout = 120
            start_time = time.time()
            while "nidlogin.login" in driver.current_url or "nid.naver.com" in driver.current_url:
                if time.time() - start_time > timeout:
                    raise Exception("로그인 대기 시간 초과로 작업을 중단합니다.")
                print(f"[로그인 대기] 크롬 창에서 직접 로그인을 완료해 주세요. (남은 대기: {int(timeout - (time.time() - start_time))}초)")
                time.sleep(3)

            # 수동 로그인 완료 후 쿠키 저장
            save_cookies(driver, uid)
            driver.get(f"https://blog.naver.com/{uid}?Redirect=Write")
            time.sleep(2)
        print("✅ 로그인 상태가 성공적으로 인증되었습니다.")
    else:
        print("✅ 기존 로그인 세션이 유효합니다. (자동/수동 로그인 건너뜀)")
        save_cookies(driver, uid)  # 세션 갱신

def write_post(driver, uid, title, content, tags=""):
    print("📝 글쓰기 페이지로 이동 중...")
    driver.get(f"https://blog.naver.com/{uid}?Redirect=Write")
    time.sleep(3)
    
    wait = WebDriverWait(driver, 10)
    
    # mainFrame 프레임으로 전환
    wait.until(EC.presence_of_element_located((By.ID, "mainFrame")))
    driver.switch_to.frame("mainFrame")
    time.sleep(1)
    
    # 팝업창 닫기 (임시저장 확인 팝업 등)
    try:
        cancel_btn = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".se-popup-button-cancel"))
        )
        cancel_btn.click()
        print("[에디터] 임시저장 팝업을 닫았습니다.")
        time.sleep(1)
    except Exception:
        pass

    # 도움말/안내 팝업 닫기
    popup_selectors = [
        ".se-help-panel-close-button",
        "[class*='help-panel-close']",
        ".se-popup-button-close",
        "[class*='popup-button-close']"
    ]
    for selector in popup_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed():
                btn.click()
                print(f"[에디터] 도움말/안내 팝업 닫음: {selector}")
                time.sleep(0.5)
        except Exception:
            pass

    # 팝업이 닫히고 레이아웃이 정돈될 때까지 대기
    time.sleep(1.5)

    # 제목 입력
    title_el = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".se-title-text"))
    )
    clipboard_paste(driver, title_el, title, force_plain=True)
    
    # 본문 입력
    body_el = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text .se-text-paragraph"))
    )
    clipboard_paste(driver, body_el, content)
    time.sleep(1.0)

    # 에디터 태그 입력 (발행 전 태그 섹션)
    if tags:
        tag_list = re.findall(r"#?([^\s#]+)", tags)
        tag_list = [t for t in tag_list if t]
        tag_entered = False
        tag_selectors = [
            ".se-tag-input",
            ".tag-input",
            "input.se_input_text",
            ".se_tag input",
            "input[placeholder*='태그']",
            "input[placeholder*='tag']",
            ".tag_area input",
            ".se-section-tag input",
        ]
        for sel in tag_selectors:
            try:
                tag_el = driver.find_element(By.CSS_SELECTOR, sel)
                if tag_el.is_displayed():
                    for tag in tag_list:
                        clipboard_paste(driver, tag_el, tag, force_plain=True)
                        time.sleep(0.2)
                        tag_el.send_keys(Keys.RETURN)
                        time.sleep(0.2)
                    tag_entered = True
                    print(f"[태그] 에디터 태그 섹션에 {len(tag_list)}개 입력 완료")
                    break
            except Exception:
                continue
        if not tag_entered:
            # JavaScript 기반 탐색
            js_find_tag = """
            var inputs = document.querySelectorAll('input');
            for (var i=0; i<inputs.length; i++){
                var ph = (inputs[i].placeholder||'').toLowerCase();
                if (ph.indexOf('태그')!==-1 || ph.indexOf('tag')!==-1){
                    return inputs[i];
                }
            }
            return null;
            """
            try:
                tag_el = driver.execute_script(js_find_tag)
                if tag_el:
                    for tag in tag_list:
                        clipboard_paste(driver, tag_el, tag, force_plain=True)
                        time.sleep(0.2)
                        tag_el.send_keys(Keys.RETURN)
                        time.sleep(0.2)
                    tag_entered = True
                    print(f"[태그] JS 탐색으로 {len(tag_list)}개 입력 완료")
            except Exception as e:
                print(f"[태그] JS 탐색 실패: {e}")
        if not tag_entered:
            print("⚠️ [태그] 에디터 태그 입력 필드를 찾지 못했습니다. 발행 설정 창에서 재시도합니다.")

    print("📤 글 발행 처리 중...")
    # 1. 상단 발행 버튼 클릭
    publish_btn = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "button[class*='publish_btn']"))
    )
    # 스크롤 및 포커스
    driver.execute_script("arguments[0].scrollIntoView(true);", publish_btn)
    time.sleep(0.5)
    try:
        driver.execute_script("arguments[0].click();", publish_btn)
        print("[발행] 상단 '발행' 버튼 클릭 성공 (JS 클릭)")
    except Exception:
        publish_btn.click()
        print("[발행] 상단 '발행' 버튼 클릭 성공 (일반 클릭)")
    time.sleep(1.5)
    
    # 2. 발행 설정 레이어에서 "비공개" 옵션 선택
    print("[발행] 비공개 옵션을 선택합니다...")
    private_set = False
    try:
        # 방법 1: CSS 클래스 기반 비공개 라디오/라벨 탐색
        private_selectors = [
            ".se-publish-option-visibility .se-publish-option-private",
            ".se-publish-visibility-item.se-publish-visibility-private",
            "label.se-publish-option-item[data-value='0']",
            "label[for*='private']",
            ".se-publish-private-option",
        ]
        for sel in private_selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    private_set = True
                    print(f"[발행] 비공개 옵션 선택 성공 (CSS: {sel})")
                    break
            except Exception:
                continue

        # 방법 2: 텍스트 내용으로 "비공개" 라벨/버튼 탐색
        if not private_set:
            js_click_private = """
            var labels = document.querySelectorAll(
                '.se-publish-option label, .se-publish-setting label, ' +
                '.se-popup-publish-option label, [class*="publish"] label, ' +
                '[class*="visibility"] label, [class*="option"] span'
            );
            for (var i = 0; i < labels.length; i++) {
                var txt = labels[i].textContent.trim();
                if (txt === '비공개' || txt.indexOf('비공개') !== -1) {
                    labels[i].click();
                    return 'ok';
                }
            }
            // input[type=radio] 탐색 (value 기반)
            var radios = document.querySelectorAll('input[type="radio"]');
            for (var j = 0; j < radios.length; j++) {
                var lbl = radios[j].parentElement;
                if (lbl && lbl.textContent.indexOf('비공개') !== -1) {
                    radios[j].click();
                    return 'ok';
                }
            }
            return 'not_found';
            """
            result = driver.execute_script(js_click_private)
            if result == 'ok':
                private_set = True
                print("[발행] 비공개 옵션 선택 성공 (JS 텍스트 탐색)")

        # 방법 3: XPath로 "비공개" 텍스트를 포함하는 클릭 가능 요소 탐색
        if not private_set:
            try:
                xpath_targets = [
                    "//label[contains(text(), '비공개')]",
                    "//span[contains(text(), '비공개')]/ancestor::label",
                    "//span[contains(text(), '비공개')]",
                    "//*[contains(@class, 'publish')]//*[contains(text(), '비공개')]",
                ]
                for xp in xpath_targets:
                    try:
                        el = driver.find_element(By.XPATH, xp)
                        if el.is_displayed():
                            driver.execute_script("arguments[0].click();", el)
                            private_set = True
                            print(f"[발행] 비공개 옵션 선택 성공 (XPath)")
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not private_set:
            print("⚠️ [발행] 비공개 옵션을 자동으로 찾지 못했습니다. 수동으로 확인해 주세요.")
    except Exception as e:
        print(f"⚠️ [발행] 비공개 설정 중 오류: {e}")

    time.sleep(1.0)

    # 2-1. 발행 설정 패널 내 태그 입력 (에디터 태그 섹션에서 실패했을 경우 포함)
    if tags:
        tag_list = re.findall(r"#?([^\s#]+)", tags)
        tag_list = [t for t in tag_list if t]
        publish_tag_selectors = [
            ".se-publish-tag-area input",
            ".se-publish-section-tag input",
            ".publish_tag_wrap input",
            "input[class*='publish'][class*='tag']",
            ".se-popup-tag-input",
            "input[placeholder*='태그']",
            "input[placeholder*='tag']",
        ]
        publish_tag_entered = False
        for sel in publish_tag_selectors:
            try:
                tag_el = driver.find_element(By.CSS_SELECTOR, sel)
                if tag_el.is_displayed():
                    for tag in tag_list:
                        clipboard_paste(driver, tag_el, tag, force_plain=True)
                        time.sleep(0.2)
                        tag_el.send_keys(Keys.RETURN)
                        time.sleep(0.2)
                    publish_tag_entered = True
                    print(f"[태그] 발행 설정 패널에 {len(tag_list)}개 태그 입력 완료")
                    break
            except Exception:
                continue
        if not publish_tag_entered:
            js_publish_tag = """
            var inputs = document.querySelectorAll('input');
            for (var i=0; i<inputs.length; i++){
                var ph = (inputs[i].placeholder||'').toLowerCase();
                if (ph.indexOf('태그')!==-1 || ph.indexOf('tag')!==-1){
                    return inputs[i];
                }
            }
            return null;
            """
            try:
                tag_el = driver.execute_script(js_publish_tag)
                if tag_el:
                    for tag in tag_list:
                        clipboard_paste(driver, tag_el, tag, force_plain=True)
                        time.sleep(0.2)
                        tag_el.send_keys(Keys.RETURN)
                        time.sleep(0.2)
                    print(f"[태그] JS 탐색으로 발행 패널 태그 {len(tag_list)}개 입력 완료")
            except Exception as e:
                print(f"[태그] 발행 패널 태그 입력 실패: {e}")

    time.sleep(0.5)

    # 3. 최종 발행 확인 버튼 클릭 (발행 레이어 내부 버튼 타겟팅)
    confirm_btn = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".se-publish-submit-button, button[class*='confirm_btn']"))
    )
    time.sleep(1.0)  # 레이어 애니메이션 대기
    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
    except Exception:
        pass
    time.sleep(0.5)
    try:
        driver.execute_script("arguments[0].click();", confirm_btn)
        print("[발행] 최종 발행 확인 버튼 클릭 성공 (JS 클릭)")
    except Exception:
        confirm_btn.click()
        print("[발행] 최종 발행 확인 버튼 클릭 성공 (일반 클릭)")
    time.sleep(3)
    
    url = get_published_url(driver, uid)
    print(f"✅ 글 발행 완료! URL: {url}")
    return url

def get_published_url(driver, uid):
    """발행 완료 후 리다이렉션된 글 번호 기반의 최종 캐노니컬 URL 추출"""
    import re
    from selenium.webdriver.common.by import By
    fallback_url = f"https://blog.naver.com/{uid}"
    
    try:
        start_time = time.time()
        # 최대 25초 동안 대기하며 최종 블로그 리다이렉트 URL 확인
        while time.time() - start_time < 25:
            try:
                try:
                    driver.switch_to.default_content()
                    current_url = driver.current_url
                except Exception as drv_err:
                    print(f"[URL 감지 대기] 드라이버 일시적 오류 (리다이렉션 중): {drv_err}")
                    time.sleep(1.0)
                    continue

                print(f"[URL 감지 대기] 현재 탑 프레임 주소: {current_url}")
                
                # 1. 탑 프레임 URL 자체에 글번호가 포함된 경우 체크 (예: blog.naver.com/id/123456789)
                path_match = re.search(r'blog\.naver\.com/([^/]+)/(\d+)', current_url, re.IGNORECASE)
                if path_match:
                    blog_id = path_match.group(1)
                    log_no = path_match.group(2)
                    clean_url = f"https://blog.naver.com/{blog_id}/{log_no}"
                    print(f"[URL 감지] 탑 프레임 경로에서 글 번호 추출 성공! 최종 주소: {clean_url}")
                    return clean_url
                
                # 2. 탑 프레임 URL에 logNo 파라미터가 있는 경우 (예: PostView.naver?blogId=...&logNo=12345)
                param_match = re.search(r'[?&]logNo=(\d+)', current_url, re.IGNORECASE)
                if param_match:
                    log_no = param_match.group(1)
                    id_match = re.search(r'[?&]blogId=([^&]+)', current_url, re.IGNORECASE)
                    blog_id = id_match.group(1) if id_match else uid
                    clean_url = f"https://blog.naver.com/{blog_id}/{log_no}"
                    print(f"[URL 감지] 탑 프레임 파라미터에서 글 번호 추출 성공! 최종 주소: {clean_url}")
                    return clean_url
                
                # 3. 탑 프레임 내 <link rel="canonical"> 엘리먼트 체크
                try:
                    canonical_el = driver.find_elements(By.XPATH, "//link[@rel='canonical']")
                    if canonical_el:
                        canonical_url = canonical_el[0].get_attribute("href")
                        if canonical_url:
                            print(f"[URL 감지] 탑 프레임 canonical 태그 발견: {canonical_url}")
                            path_match = re.search(r'blog\.naver\.com/([^/]+)/(\d+)', canonical_url, re.IGNORECASE)
                            if path_match:
                                blog_id = path_match.group(1)
                                log_no = path_match.group(2)
                                clean_url = f"https://blog.naver.com/{blog_id}/{log_no}"
                                print(f"[URL 감지] 탑 프레임 canonical에서 글 번호 추출 성공! 최종 주소: {clean_url}")
                                return clean_url
                except Exception as can_err:
                    print(f"[URL 감지] 탑 프레임 canonical 조회 에러: {can_err}")

                # 4. 탑 프레임에는 없지만, iframe 구조 내에 있는 경우 (기존 호환성 대비 fallback)
                if "blog.naver.com" in current_url and "write" not in current_url.lower() and "redirect" not in current_url.lower():
                    try:
                        driver.switch_to.frame("mainFrame")
                        iframe_url = driver.execute_script("return window.location.href;")
                        print(f"[URL 감지] mainFrame 내부 주소: {iframe_url}")
                        
                        iframe_match = re.search(r'[?&]logNo=(\d+)', iframe_url, re.IGNORECASE)
                        if iframe_match:
                            log_no = iframe_match.group(1)
                            id_match = re.search(r'[?&]blogId=([^&]+)', iframe_url, re.IGNORECASE)
                            blog_id = id_match.group(1) if id_match else uid
                            clean_url = f"https://blog.naver.com/{blog_id}/{log_no}"
                            print(f"[URL 감지] iframe 내부에서 글 번호 추출 성공! 최종 주소: {clean_url}")
                            return clean_url
                        
                        # mainFrame 내부의 <link rel="canonical"> 엘리먼트 체크
                        canonical_el = driver.find_elements(By.XPATH, "//link[@rel='canonical']")
                        if canonical_el:
                            canonical_url = canonical_el[0].get_attribute("href")
                            if canonical_url:
                                print(f"[URL 감지] mainFrame canonical 태그 발견: {canonical_url}")
                                path_match = re.search(r'blog\.naver\.com/([^/]+)/(\d+)', canonical_url, re.IGNORECASE)
                                if path_match:
                                    blog_id = path_match.group(1)
                                    log_no = path_match.group(2)
                                    clean_url = f"https://blog.naver.com/{blog_id}/{log_no}"
                                    print(f"[URL 감지] iframe canonical에서 글 번호 추출 성공! 최종 주소: {clean_url}")
                                    return clean_url
                    except Exception as frame_err:
                        print(f"[URL 감지] iframe 전환 또는 URL 파싱 대기: {frame_err}")
            except Exception as loop_err:
                print(f"[URL 감지 루프 내 에러] {loop_err}")
            time.sleep(1.0)
    except Exception as e:
        print(f"[URL 추출 오류] {e}")
        
    print(f"[URL 추출 실패] 최종 URL 리다이렉션 지연으로 홈 주소로 대체합니다: {fallback_url}")
    return fallback_url

if __name__ == "__main__":
    # 평문 설정이 있다면 자동 마이그레이션 실행
    migrate_config()

    parser = argparse.ArgumentParser(description="네이버 블로그 자동 포스팅")
    parser.add_argument("--id",      default=None, help="네이버 아이디")
    parser.add_argument("--pw",      default=None, help="네이버 비밀번호")
    parser.add_argument("--title",   default=None, help="블로그 글 제목")
    parser.add_argument("--content", default=None, help="블로그 글 본문")
    args = parser.parse_args()

    cfg = load_config()
    default_id = args.id or cfg.get("naver_id") or ""
    default_pw = args.pw or cfg.get("naver_pw") or ""

    uid = default_id
    if not uid:
        uid = input("네이버 아이디를 입력하세요: ").strip()

    if uid == default_id and default_pw:
        upw = default_pw
        print("🔑 기존에 저장된 비밀번호를 사용합니다.")
    else:
        upw = masked_input("네이버 비밀번호를 입력하세요: ").strip()

    title   = args.title   or input("글 제목을 입력하세요: ").strip()
    content = args.content or input("글 본문을 입력하세요: ").strip()

    # 입력받은 아이디/비밀번호가 기존 설정과 다를 경우 암호화하여 저장
    if (uid != cfg.get("naver_id")) or (upw != cfg.get("naver_pw")):
        cfg["naver_id"] = uid
        cfg["naver_pw"] = upw
        save_config(cfg)
        print("🔒 네이버 계정 정보가 안전하게 암호화되어 로컬에 저장되었습니다.")

    driver = None
    try:
        driver = get_driver(uid)
        ensure_logged_in(driver, uid, upw)
        write_post(driver, uid, title, content)
    except Exception as e:
        import traceback
        print(f"\n❌ 포스팅 중 에러가 발생했습니다:\n{e}")
        print("\n[상세 에러 로그]")
        traceback.print_exc()
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print("\n" + "="*50)
        input("종료하려면 Enter 키를 누르십시오...")
