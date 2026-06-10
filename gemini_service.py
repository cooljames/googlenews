# pyright: reportMissingImports=false
"""
gemini_service.py — Google Gemini API와의 연동을 전담하는 서비스 모듈
"""
import re
import json
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-3.1-flash-lite"
KST = timezone(timedelta(hours=9))

def _clean_json(raw: str) -> str:
    return re.sub(
        r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.IGNORECASE
    ).strip()

def generate_blog_content(api_key: str, prompt_text: str, model_id: str = DEFAULT_MODEL):
    """주어진 프롬프트로 네이버 블로그 콘텐츠 초안을 생성합니다."""
    client = genai.Client(api_key=api_key)
    now = datetime.now(KST)
    date_str = f"{now.year}년 {now.month}월 {now.day}일"
    
    system_instruction = f"""
당신은 네이버 블로그 포스팅을 전문으로 하는 지식이 풍부하고 유려한 에디터입니다.
사용자가 제공하는 주제/프롬프트에 맞추어 전문적이면서도 친근한 어투로 한국어 글을 작성하세요.
문단 구분을 확실하게 하여 가독성을 높여 주시기 바랍니다.

반드시 아래 JSON 스키마 형식으로만 응답하며, 코드 블록 없이 순수 JSON만 출력하세요.

{{
  "title": "블로그 포스트 제목",
  "content": "풍부하고 상세한 본문 내용 (단락 구분은 \\n 활용)"
}}

규칙:
- title: 반드시 "{date_str} [주제/핵심 키워드]" 형식으로 작성하세요.
  예: "{date_str} AI 코딩 툴 트렌드와 생산성 향상 비결"
  제목 길이는 핵심 어휘 위주로 간결하게 공백 포함 40자 이내(평소의 2/3 길이)로 작성해 주세요.
"""
    response = client.models.generate_content(
        model=model_id,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    raw = _clean_json(response.text or "")
    try:
        data = json.loads(raw)
        return data.get("title", f"포스트: {prompt_text[:15]}..."), data.get("content", raw)
    except Exception as json_err:
        print(f"[경고] JSON 파싱 폴백: {json_err}")
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        if lines:
            return lines[0].replace("#", "").replace('"', "").strip(), "\n\n".join(lines[1:])
        return f"포스트: {prompt_text[:15]}...", raw

def generate_hashtags(api_key: str, model_id: str, content_text: str) -> str:
    """본문 내용을 분석하여 12~15개의 관련 한국어 해시태그를 생성합니다."""
    client = genai.Client(api_key=api_key)
    now = datetime.now(KST)
    date_tag = f"#{now.year}년{now.month}월{now.day}일"
    
    system_instruction = f"""
당신은 블로그 마케팅 전문가입니다.
제공된 본문 텍스트에서 가장 중요한 문장 12~15개에 상응하는, 각 문장의 핵심 의미나 단어를 포착하여 12개 이상 15개 이하의 해시태그를 한국어로 생성하십시오.

규칙:
- 첫 번째 해시태그는 반드시 '{date_tag}'이어야 합니다.
- 전체 해시태그 개수는 반드시 12개에서 15개 사이여야 합니다.
- 각 해시태그는 '#'로 시작해야 하며, 띄어쓰기 없이 단어나 짧은 어구로 구성하십시오. (예: #코스피상승, #반도체전망)
- 해시태그 간에는 공백으로 구분하십시오.
- 다른 설명이나 멘트 없이 오직 해시태그 목록만 반환하십시오.
"""
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=content_text[:8000],  # 입력 제한 방지
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.5,
            ),
        )
        tags = (response.text or "").strip()
        found_tags = re.findall(r"#[^\s#]+", tags)
        
        # 첫 번째 태그를 강제로 date_tag로 설정하거나 맨 앞에 추가
        if date_tag not in found_tags:
            found_tags.insert(0, date_tag)
        else:
            # 순서 보장을 위해 기존 위치에서 제거하고 맨 앞으로
            found_tags.remove(date_tag)
            found_tags.insert(0, date_tag)
            
        if 12 <= len(found_tags) <= 15:
            return " ".join(found_tags)
        
        # 개수 부족 시 보정
        if len(found_tags) < 12:
            default_tags = ["#주식시황", "#금융뉴스", "#증시분석", "#거시경제", "#투자정보", "#시장분석", "#테크뉴스", "#시장동향", "#블로그포스팅"]
            for dt in default_tags:
                if dt not in found_tags:
                    found_tags.append(dt)
                    if len(found_tags) >= 12:
                        break
        return " ".join(found_tags[:15])
    except Exception as e:
        print(f"[경고] 해시태그 생성 중 오류: {e}")
        return f"{date_tag} #주식시황 #증시분석 #금융뉴스 #거시경제 #재테크 #시장전망 #투자정보 #주식투자 #주가분석 #테크트렌드 #AI기술 #IT뉴스"

def generate_news_outline(api_key: str, art_text: str, n_articles: int, model_id: str = DEFAULT_MODEL) -> dict:
    """뉴스 기사 텍스트를 분석하여 기사 개수와 일치하는 소제목 목차를 생성합니다."""
    client = genai.Client(api_key=api_key)
    now = datetime.now(KST)
    date_str = f"{now.year}년 {now.month}월 {now.day}일"
    
    sys_inst = f"""
당신은 뉴스 기사 분석 전문 에디터입니다.
제공된 기사들을 바탕으로 아래 JSON 형식으로만 응답하세요.
코드 블록 없이 순수 JSON만 출력하세요.

{{
  "title": "분석 포스트 제목",
  "subheadings": ["소제목1", "소제목2", ...],
  "tags": ["태그1", ..., "태그12이상"]
}}

규칙:
- subheadings: 기사 {n_articles}개에 맞게 정확히 {n_articles}개 문자열 (분석 내용 없이 소제목만)
- tags: 핵심 키워드 12개 이상 15개 이하, 한국어 단어
- title: 반드시 "{date_str} [핵심 키워드/시황]" 형식으로 작성하세요.
  예: "{date_str} 코스피 급락과 반도체 우려, 고환율 속 증시 조정 분석"
  제목 길이는 너무 길지 않게 간결하고 핵심적인 어휘만 사용하여 2/3 정도의 길이(공백 포함 40자 이내)로 작성해 주세요.
"""
    resp = client.models.generate_content(
        model=model_id,
        contents=f"다음 기사들의 분석 포스팅 목차를 작성해 주세요:\n{art_text}",
        config=types.GenerateContentConfig(
            system_instruction=sys_inst,
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    try:
        data = json.loads(_clean_json(resp.text or ""))
        subs = data.get("subheadings", [])
        if subs and isinstance(subs[0], dict):
            subs = [s.get("title", "") for s in subs]
        data["subheadings"] = subs
        return data
    except Exception:
        return {
            "title": f"{date_str} 뉴스 분석 포스팅",
            "subheadings": [f"기사 {i} 분석" for i in range(1, n_articles + 1)],
            "tags": [],
        }

def generate_report_title(api_key: str, model_id: str, content_text: str) -> str:
    """본문 내용을 분석하여 YYYY년 M월 D일 [핵심 키워드] 형식의 제목을 생성합니다."""
    client = genai.Client(api_key=api_key)
    now = datetime.now(KST)
    date_str = f"{now.year}년 {now.month}월 {now.day}일"
    
    sys_inst = f"""
당신은 주식 시장 분석 전문 에디터이자 블로그 마케팅 전문가입니다.
제공된 주식/시황 분석 리포트의 본문 내용을 바탕으로, 가장 중요한 핵심 키워드와 시장 시황을 요약하여 블로그 제목을 한국어로 작성하십시오.

규칙:
- 반드시 "{date_str} [핵심 키워드/시황]" 형식으로 작성하세요.
  예: "{date_str} 코스피 급락과 반도체 우려, 고환율 속 증시 조정 분석"
- 제목 길이는 너무 길지 않게 간결하고 핵심적인 어휘만 사용하여 2/3 정도의 길이(공백 포함 40자 이내)로 작성해 주세요.
- 다른 설명이나 멘트 없이 오직 제목 텍스트만 반환하십시오.
"""
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=content_text[:4000],
            config=types.GenerateContentConfig(
                system_instruction=sys_inst,
                temperature=0.5,
            ),
        )
        return (response.text or f"주식 리포트 {date_str}").strip()
    except Exception as e:
        print(f"[경고] 리포트 제목 생성 중 오류: {e}")
        return f"주식 리포트 {date_str}"

def generate_news_analyses(api_key: str, art_text: str, sub_titles: list, model_id: str = DEFAULT_MODEL) -> list:
    """모든 소제목에 대한 심층 분석을 1회의 API 호출로 처리합니다."""
    client = genai.Client(api_key=api_key)
    n = len(sub_titles)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(sub_titles))

    sys_inst = f"""
당신은 뉴스 기사 분석 전문 에디터입니다.
제공된 기사들과 소제목 목록을 바탕으로 각 소제목에 대한 심층 분석을 한 번에 작성하세요.
코드 블록 없이 순수 JSON만 출력하세요.

{{
  "analyses": [
    {{"title": "소제목", "analysis": "분석 내용"}},
    ...
  ]
}}

규칙:
- analyses 배열은 반드시 {n}개 (입력 소제목 순서 동일)
- 각 title은 입력된 소제목 그대로 사용
- 각 analysis: 수치(%, 금액, 연도, 순위) 반드시 포함, 700자 내외
- 객관적 사실 기반, 한국어
- 본문 내용 중 중요 단어는 반드시 **중요단어** 형식으로 볼드(bold) 처리해 주세요.
- 수치나 변화량의 경우, 상승/증가 등은 가능한 한 '+' 기호를, 하락/감소 등은 '-' 기호를 숫자 앞에 붙여서 표현해 주세요. (예: +3.42%, -0.10%)
"""
    user_message = (
        f"기사 목록:\n{art_text}\n\n"
        f"소제목 목록 ({n}개):\n{numbered}\n\n"
        "위 기사를 바탕으로 각 소제목에 대한 분석을 작성해 주세요."
    )

    resp = client.models.generate_content(
        model=model_id,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=sys_inst,
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )

    try:
        data = json.loads(_clean_json(resp.text or ""))
        raw_list = data.get("analyses", [])
    except Exception as e:
        print(f"[경고] 일괄 분석 JSON 파싱 실패: {e}")
        raw_list = []

    # 결과를 소제목 순서에 맞게 정렬 (누락 분 보완)
    result = []
    for i, sub_title in enumerate(sub_titles):
        if i < len(raw_list):
            item = raw_list[i]
            analysis = item.get("analysis", "(분석 내용 없음)")
        else:
            analysis = "(분석 누락)"
        result.append((sub_title, analysis))

    return result
