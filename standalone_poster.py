# pyright: reportMissingImports=false
"""
standalone_poster.py — 외부 모듈 의존성 없이 단독 실행 가능한 스마트에디터 ONE 자동 포스팅 스크립트.
"""
import os
import time
import pyperclip
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

USER_ID  = "네이버아이디"
USER_PW  = "비밀번호"
TITLE    = "자동 작성 테스트 글 (스마트에디터 ONE)"
CONTENT  = "이 글은 마이그레이션된 Python Selenium 스크립트로 자동 작성되었습니다."

def get_driver(chrome_profile_path=None):
    # 크롬 사용자 프로필 디렉토리 구성 (CAPTCHA 및 기기 인증 우회의 핵심)
    if chrome_profile_path is None:
        # JamesBoard 본체(NaverBlogAutoPoster)와 동일한 AppData 경로를 사용하여 쿠키 세션을 완벽 공유
        app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        app_dir = os.path.join(app_data, "NaverBlogAutoPoster")
        chrome_profile_path = os.path.join(app_dir, "chrome_profile")
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

    options = Options()
    options.add_argument(f"--user-data-dir={chrome_profile_path}")
    options.add_argument("--profile-directory=Default")
    
    # 봇 탐지 우회 기본 옵션들
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    service = Service()
    if os.name == 'nt':
        service.creation_flags = 0x08000000  # CREATE_NO_WINDOW
        
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.maximize_window()
    except Exception:
        pass
    
    # webdriver 속성 숨기기 및 navigator 은닉
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
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

def clipboard_paste(driver, element, text):
    """클립보드를 통한 복사 붙여넣기로 캡차(CAPTCHA) 방지"""
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
        return True
    except Exception as e:
        print(f"❌ 자동 로그인 시도 중 에러 발생: {e}")
        return False

def ensure_logged_in(driver, uid, upw):
    """로그인 상태 확인 및 필요시 로그인 진행"""
    print("[상태 체크] 네이버 로그인 세션 유효성을 확인합니다...")
    driver.get(f"https://blog.naver.com/{uid}?Redirect=Write")
    time.sleep(2)

    current_url = driver.current_url
    if "nidlogin.login" in current_url or "nid.naver.com" in current_url:
        print("[상태 체크] 로그인이 필요합니다. 로그인 프로세스를 개시합니다.")
        success = naver_login(driver, uid, upw)
        
        # 만약 로그인 시도가 실패한 경우 (캡차 팝업이 뜬 경우), 사용자가 크롬창에서 직접 로그인할 수 있게 120초 동안 대기
        if not success:
            timeout = 120
            start_time = time.time()
            while "nidlogin.login" in driver.current_url or "nid.naver.com" in driver.current_url:
                if time.time() - start_time > timeout:
                    raise Exception("로그인 대기 시간 초과로 작업을 중단합니다.")
                print(f"[로그인 대기] 캡차가 발생했거나 로그인이 필요합니다. 크롬 브라우저 창에서 로그인을 직접 완료해 주세요. (남은 대기 시간: {int(timeout - (time.time() - start_time))}초)")
                time.sleep(3)
            
            # 수동 로그인 완료 후 에디터로 다시 접속
            driver.get(f"https://blog.naver.com/{uid}?Redirect=Write")
            time.sleep(2)
        print("✅ 로그인 상태가 성공적으로 인증되었습니다.")
    else:
        print("✅ 기존 로그인 세션이 유효합니다. (자동/수동 로그인 건너뜀)")

def write_post(driver, uid, title, content):
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
    clipboard_paste(driver, title_el, title)
    
    # 본문 입력
    body_el = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".se-component.se-text .se-text-paragraph"))
    )
    clipboard_paste(driver, body_el, content)
    
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
    
    # 2. 최종 발행 확인 버튼 클릭 (발행 레이어 내부 버튼 타겟팅)
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
    driver = None
    try:
        uid = USER_ID
        if not uid or uid == "네이버아이디":
            uid = input("네이버 아이디를 입력하세요: ").strip()
            
        upw = USER_PW
        if not upw or upw == "비밀번호":
            try:
                import getpass
                upw = getpass.getpass("네이버 비밀번호를 입력하세요: ").strip()
            except Exception:
                upw = input("네이버 비밀번호를 입력하세요: ").strip()

        driver = get_driver()
        ensure_logged_in(driver, uid, upw)
        write_post(driver, uid, TITLE, CONTENT)
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
