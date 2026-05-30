# Naver Blog Auto Poster

네이버 블로그 스마트에디터 ONE에 자동으로 글을 발행하는 단독 실행 스크립트입니다.  
외부 서버나 별도 설치 없이 `.exe` 하나로 동작합니다.

## 주요 기능

- **자동 로그인** — 네이버 ID/PW로 로그인하며, 세션 쿠키를 로컬에 저장해 다음 실행 시 재로그인 생략
- **봇 감지 우회** — `undetected_chromedriver`로 ChromeDriver 바이너리를 자동 패치, 네이버 봇 감지 방어
- **클립보드 붙여넣기** — ID·PW·제목·본문을 직접 타이핑 대신 클립보드를 통해 입력하여 CAPTCHA 회피
- **발행 URL 추출** — 발행 완료 후 리다이렉션을 추적해 최종 블로그 글 URL을 자동 반환
- **계정별 Chrome 프로필 분리** — 여러 계정을 동시에 운영해도 세션이 충돌하지 않음
- **단독 실행 파일** — PyInstaller로 빌드된 `standalone_poster.exe` 하나로 Python 환경 없이 구동

## 사용법

### 실행 파일 (권장)

`dist/standalone_poster.exe`를 실행합니다.

```
standalone_poster.exe --id <네이버ID> --pw <비밀번호> --title <글제목> --content <본문>
```

인수를 생략하면 실행 시 터미널에서 순서대로 입력받습니다 (비밀번호는 `*`로 마스킹).

### Python으로 직접 실행

```bash
pip install selenium undetected-chromedriver pyperclip
python standalone_poster.py --id myid --pw mypassword --title "오늘의 일기" --content "안녕하세요!"
```

## 인수 설명

| 인수 | 설명 | 필수 여부 |
|------|------|-----------|
| `--id` | 네이버 아이디 | 선택 (생략 시 입력 프롬프트) |
| `--pw` | 네이버 비밀번호 | 선택 (생략 시 마스킹 입력) |
| `--title` | 블로그 글 제목 | 선택 (생략 시 입력 프롬프트) |
| `--content` | 블로그 글 본문 | 선택 (생략 시 입력 프롬프트) |

## 동작 흐름

```
1. Chrome 브라우저 실행 (계정별 프로필 디렉터리 사용)
2. 저장된 쿠키로 세션 복원 시도
3. 로그인 필요 시 자동 로그인 진행
   └─ CAPTCHA 발생 시 120초 내 수동 로그인 대기
4. 스마트에디터 ONE 글쓰기 페이지 열기
5. 제목·본문 클립보드로 입력
6. 발행 버튼 클릭 → 최종 발행 확인
7. 발행된 글 URL 추출 및 출력
```

## 세션 쿠키 저장 위치

```
%LOCALAPPDATA%\NaverBlogAutoPoster\cookies_<네이버ID>.json
%LOCALAPPDATA%\NaverBlogAutoPoster\chrome_profile_<네이버ID>\
```

## 빌드 방법

```bash
pip install pyinstaller
pyinstaller standalone_poster.spec
```

빌드 결과물은 `dist/standalone_poster.exe`에 생성됩니다.

## 의존성

| 패키지 | 역할 |
|--------|------|
| `selenium` | 브라우저 자동화 |
| `undetected-chromedriver` | ChromeDriver 봇 감지 우회 패치 |
| `pyperclip` | 클립보드 복사·붙여넣기 |

> Chrome 브라우저가 설치되어 있어야 합니다. ChromeDriver는 `undetected_chromedriver`가 자동으로 다운로드·패치합니다.

## 주의사항

- Windows 전용입니다 (비밀번호 마스킹에 `msvcrt` 사용).
- 네이버 정책 변경으로 CSS 셀렉터가 바뀔 경우 `write_post` 함수의 셀렉터를 수정해야 합니다.
- 자동화 도구 사용은 네이버 이용약관을 준수하는 범위 내에서 활용하세요.
