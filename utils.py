# pyright: reportMissingImports=false
"""
utils.py — HTML 분석 및 로컬 이미지 base64 변환 등 독립형 유틸리티 함수 모음
"""
import re
import os
import base64
import html as py_html

def parse_html_report(html_content: str) -> tuple:
    """HTML 보고서에서 제목과 본문 텍스트를 파싱하여 추출합니다."""
    # 1. 제목 추출 (title 태그 우선, 없을 시 h1 태그)
    title = "주식/ETF 뉴스 리포트"
    title_match = re.search(r"<title>(.*?)</title>", html_content, re.IGNORECASE)
    if title_match:
        title = py_html.unescape(title_match.group(1).strip())
    else:
        h1_match = re.search(r"<h1>(.*?)</h1>", html_content, re.IGNORECASE)
        if h1_match:
            title = py_html.unescape(re.sub(r"<[^>]+>", "", h1_match.group(1)).strip())

    # 2. 본문 추출
    # HTML 주석 제거
    body_content = re.sub(r"<!--.*?-->", "", html_content, flags=re.DOTALL)
    
    # style 태그 제거
    body_content = re.sub(r"<style[^>]*>.*?</style>", "", body_content, flags=re.DOTALL | re.IGNORECASE)
    # head 태그 제거
    body_content = re.sub(r"<head[^>]*>.*?</head>", "", body_content, flags=re.DOTALL | re.IGNORECASE)
    # script 태그 제거
    body_content = re.sub(r"<script[^>]*>.*?</script>", "", body_content, flags=re.DOTALL | re.IGNORECASE)

    # 테이블 셀 구분 보존: th, td 태그 앞에 공백/구분선 추가
    body_content = re.sub(r"<th[^>]*>", " | ", body_content, flags=re.IGNORECASE)
    body_content = re.sub(r"<td[^>]*>", " | ", body_content, flags=re.IGNORECASE)

    # 주요 블록 태그들을 줄바꿈으로 치환하여 단락 보존
    body_content = re.sub(r"<(p|tr|h1|h2|h3|div|li)[^>]*>", "\n", body_content, flags=re.IGNORECASE)
    body_content = re.sub(r"<br[^>]*>", "\n", body_content, flags=re.IGNORECASE)
    
    # 나머지 모든 HTML 태그 제거
    body_content = re.sub(r"<[^>]+>", "", body_content)
    
    # HTML 엔티티 디코딩
    body_content = py_html.unescape(body_content)
    
    # 줄바꿈 정제 및 불필요한 연속 공백 정돈
    lines = []
    for line in body_content.split("\n"):
        line_str = line.strip()
        # 양끝 구분선 정리
        if line_str.startswith("|"):
            line_str = line_str[1:].strip()
        if line_str.endswith("|"):
            line_str = line_str[:-1].strip()
        
        # 다중 공백 제거
        line_str = re.sub(r"\s+", " ", line_str).strip()
        
        if line_str:
            lines.append(line_str)
            
    content_text = "\n\n".join(lines)
    return title, content_text

def resolve_html_images_to_base64(html_content: str) -> str:
    """HTML 내의 로컬 이미지 절대 경로를 찾아 base64 데이터 URI로 변환합니다."""
    def replace_img(match):
        img_tag = match.group(0)
        src_match = re.search(r'src=["\'](.*?)["\']', img_tag, re.IGNORECASE)
        if not src_match:
            return img_tag
            
        src = src_match.group(1)
        if src.startswith("data:"):
            return img_tag
            
        img_path = os.path.abspath(src)
        if os.path.exists(img_path):
            try:
                ext = os.path.splitext(img_path)[1].lower().replace(".", "")
                if ext == "jpg":
                    ext = "jpeg"
                with open(img_path, "rb") as img_file:
                    img_data = img_file.read()
                base64_data = base64.b64encode(img_data).decode("utf-8")
                new_src = f"data:image/{ext};base64,{base64_data}"
                return re.sub(r'src=["\'](.*?)["\']', lambda m: f'src="{new_src}"', img_tag, flags=re.IGNORECASE)
            except Exception as e:
                print(f"[경고] 이미지 base64 변환 실패 ({img_path}): {e}")
        else:
            print(f"[경고] 이미지를 찾을 수 없음: {img_path}")
        return img_tag

    return re.sub(r'<img[^>]+>', replace_img, html_content, flags=re.IGNORECASE)
