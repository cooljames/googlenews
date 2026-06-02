# Design Refactoring Plan — Neo-Brutalist UI
> 참조: 제공된 HTML (Tailwind + Neo-Brutalist 시스템)  
> 대상 파일: `gui_app.py`, `news_analyzer.py`

---

## 1. 현재 vs 목표 색상 팔레트

| 역할 | 현재 (Dark Green) | 목표 (Neo-Brutalist) | HTML 변수 |
|------|------------------|---------------------|-----------|
| 창 배경 | `#0c1b12` | `#F5F0E8` | `background` |
| 카드/섹션 배경 | `#14291c` | `#FFFFFF` | `surface-container-lowest` |
| 입력 필드 배경 | `#08120c` | `#F5F0E8` | `background` |
| 기본 텍스트 | `#e8f5e9` | `#1A1A1A` | `on-background` |
| 보조 텍스트 | `#a5d6a7` | `#4A4A4A` | `on-surface-variant` |
| 주요 버튼 배경 | `#248c51` | `#1A1A1A` | `primary` |
| 주요 버튼 텍스트 | `#e8f5e9` | `#FFFFFF` | `on-primary` |
| 강조 (Accent) | `#1d5736` | `#FFCC00` | `primary-container` |
| RSS 분석 버튼 | `#1a6b3c` | `#0055FF` | `tertiary` |
| 날짜 필터 버튼 | `#248c51` | `#0055FF` | `tertiary` |
| 경고/에러 | _(없음)_ | `#E63B2E` | `secondary` |
| 테두리 | `#223f2d` | `#1A1A1A` | `outline` |
| 호버 | `#2fa563` | `#FFCC00` | `primary-fixed` |

---

## 2. 디자인 원칙 (HTML → Tkinter 매핑)

| HTML 원칙 | Tkinter 구현 방법 |
|-----------|-----------------|
| 두꺼운 테두리 `border-4` (4px) | `bd=3, relief="solid"` |
| 오프셋 그림자 `brutal-shadow: 6px 6px #1A1A1A` | 프레임 이중 래핑으로 시뮬레이션 (우측+하단 2px 오프셋 프레임) |
| 그라디언트 금지 | Tkinter는 기본 플랫 — 유지 |
| 굵은 대문자 폰트 `font-black uppercase` | `font=("맑은 고딕", N, "bold")` + 텍스트 `.upper()` |
| 고대비 (검정↔흰색) | 배경 `#FFFFFF` + 텍스트 `#1A1A1A` |
| 액센트는 섹션당 1개만 | 버튼 색상 역할별 명확히 구분 |

---

## 3. 컴포넌트별 변경 계획

### 3-1. 창 헤더 (Header Label)
```
현재: bg_dark 배경, 흰 텍스트
목표: #1A1A1A 배경, 흰 텍스트, 하단 4px #1A1A1A 테두리
      "NAVER BLOG AUTO POSTER" → 대문자 유지
```

### 3-2. 노트북 탭 (TNotebook)
```
현재: 초록 탭, 선택 시 primary green
목표:
  - 기본 탭: #F5F0E8 배경, #1A1A1A 텍스트, bd=2 solid
  - 선택된 탭: #FFCC00 배경, #1A1A1A 텍스트
  - 탭 폰트: bold, 대문자
```

### 3-3. LabelFrame (섹션 구분)
```
현재: bg_card(#14291c), 초록 텍스트, 얇은 테두리
목표:
  - 배경: #FFFFFF
  - 텍스트: #1A1A1A, bold, 대문자
  - 테두리: bd=3, relief="solid", fg="#1A1A1A"
  - 오프셋 효과: 래핑 Frame으로 우+하 3px offset 시뮬레이션
```

### 3-4. 버튼 역할별 색상

| 버튼 | 배경 | 텍스트 | 호버 | 역할 |
|------|------|--------|------|------|
| 네이버 포스팅 | `#1A1A1A` | `#FFFFFF` | `#4A4A4A` | 기본 액션 |
| RSS 불러오기 | `#1A1A1A` | `#FFFFFF` | `#4A4A4A` | 기본 액션 |
| 분석 & 저장 | `#0055FF` | `#FFFFFF` | `#003DD6` | 주요 기능 |
| 전체 선택/해제 | `#F5F0E8` | `#1A1A1A` | `#FFCC00` | 보조 |
| 오늘/이번주/이번달 | `#FFCC00` | `#1A1A1A` | `#E6B800` | 필터 |
| 설정 저장 | `#1A1A1A` | `#FFFFFF` | `#4A4A4A` | 액션 |
| API 보기/숨기기 | `#F5F0E8` | `#1A1A1A` | `#FFCC00` | 보조 |

- 모든 버튼: `bd=0, relief="flat"` → 오프셋 효과는 `pady`, `padx`로 시각적 두께감 부여
- 버튼 텍스트: bold

### 3-5. 입력 필드 (Entry)
```
현재: bg_input(#08120c), 초록 텍스트
목표:
  - bg: #FFFFFF
  - fg: #1A1A1A
  - insertbackground: #1A1A1A
  - bd=3, relief="solid"
  - highlightthickness=0
```

### 3-6. 텍스트 영역 (Text / ScrolledText)
```
프롬프트 입력:
  - bg: #FFFFFF, fg: #1A1A1A, bd=3 solid

로그 창:
  - bg: #1A1A1A (로그 가독성 유지)
  - fg: #FFCC00 (황색 텍스트 — 브루탈리스트 터미널 느낌)
  - 테두리: bd=3, relief="solid"
```

### 3-7. 체크박스 목록 (Canvas + Checkbutton)
```
현재: 어두운 배경, 초록 텍스트
목표:
  - 홀수 행: #FFFFFF
  - 짝수 행: #F5F0E8
  - 텍스트: #1A1A1A
  - selectcolor: #FFCC00
  - activebackground: #FFCC00
```

### 3-8. Combobox (모델 선택)
```
현재: 초록 계열
목표:
  - fieldbackground: #FFFFFF
  - foreground: #1A1A1A
  - selectbackground: #FFCC00
  - selectforeground: #1A1A1A
  - 드롭다운 리스트: bg=#FFFFFF, fg=#1A1A1A
```

### 3-9. 구분선
```
현재: #223f2d (어두운 초록)
목표: #1A1A1A (굵은 검정 1px)
```

---

## 4. 오프셋 그림자 시뮬레이션 (선택 적용)

Tkinter는 CSS box-shadow 미지원. 아래 방식으로 근사:

```python
def make_brutal_frame(parent, bg_outer="#1A1A1A", bg_inner="#FFFFFF", offset=4):
    """
    outer frame(검정) 안에 inner frame(흰색)을 offset으로 배치 →
    우측+하단에 검정 테두리가 보여 브루탈 그림자 효과
    """
    outer = tk.Frame(parent, bg=bg_outer)
    inner = tk.Frame(outer, bg=bg_inner, bd=2, relief="solid")
    inner.pack(padx=(0, offset), pady=(0, offset), fill="both", expand=True)
    return outer, inner
```

→ LabelFrame 대신 이 패턴으로 주요 섹션 구성

---

## 5. 새 테마 상수 (gui_app.py 교체 대상)

```python
# Neo-Brutalist Theme
self.bg_dark      = "#F5F0E8"   # 창 배경 (Warm Off-White)
self.bg_card      = "#FFFFFF"   # 카드 배경 (Pure White)
self.bg_input     = "#FFFFFF"   # 입력 배경
self.text_light   = "#FFFFFF"   # 버튼 위 텍스트 (흰색)
self.text_dark    = "#1A1A1A"   # 일반 텍스트 (검정)
self.text_muted   = "#4A4A4A"   # 보조 텍스트
self.primary      = "#1A1A1A"   # 주요 버튼 (검정)
self.primary_text = "#FFFFFF"   # 주요 버튼 텍스트
self.accent       = "#FFCC00"   # 강조 (Vivid Yellow)
self.accent_text  = "#1A1A1A"   # 강조 위 텍스트
self.tertiary     = "#0055FF"   # RSS/분석 버튼 (Bauhaus Blue)
self.error        = "#E63B2E"   # 에러 (Signal Red)
self.border_color = "#1A1A1A"   # 테두리 (검정)
self.hover        = "#FFCC00"   # 호버 (Yellow)
self.btn_rss      = "#0055FF"   # 분석 버튼
```

---

## 6. 변경 파일 및 범위

| 파일 | 변경 범위 | 비고 |
|------|----------|------|
| `gui_app.py` | 테마 상수 전체 교체, `setup_styles()`, `build_post_tab()`, `build_settings_tab()` | 기능 코드 무변경 |
| `news_analyzer.py` | `__init__` 색상 언패킹, `build()` 위젯 색상 전부 | 기능 코드 무변경 |

---

## 7. 구현 순서

1. `gui_app.py` 테마 상수 교체
2. `setup_styles()` — TNotebook, TCombobox, TScrollbar 스타일 업데이트
3. `build_post_tab()` — 위젯 색상 적용
4. `build_settings_tab()` — 위젯 색상 적용
5. `news_analyzer.py` — 테마 수신 + 위젯 색상 적용
6. 전체 실행 테스트

---

## 8. 적용 불가 항목 (Tkinter 한계)

| HTML 요소 | 이유 | 대안 |
|-----------|------|------|
| CSS box-shadow (blurred) | Tkinter 미지원 | offset frame 패턴 |
| Border-radius (rounded) | Tkinter 미지원 | 직각 유지 (브루탈리스트에 오히려 어울림) |
| Space Grotesk 폰트 | 시스템 미설치 가능 | `맑은 고딕` bold 대체 |
| hover transition animation | Tkinter 미지원 | 즉시 색상 변경 유지 |

---

> **승인 대기 중** — 위 계획 확인 후 구현 진행하겠습니다.
