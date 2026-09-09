#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 응답 JSON 파싱 공용 모듈 - 3층 방어.

**이 파일은 `nvl-vibe-radar/llm_json.py`와 쌍둥이다. 한쪽을 고치면 반드시 다른 쪽도 고친다.**
두 저장소는 서로 import할 수 없다(레이더는 Vercel로 따로 배포된다). 그래서 같은 내용을
양쪽에 하나씩 둔다.

왜 모았나 - 2026-09-10 하루에 같은 결함을 세 번 만났다.
  - 게이트(gnews_ingest) : 제목 속 따옴표를 모델이 이스케이프하지 않아 통짜 파싱이 깨졌다(표본 8%).
  - 표기 정규화(fix_title_notation) : JSON 뒤에 설명 문장이 붙어 「Extra data」로
    586건 중 84건째에서 중단됐다.
  - 시제 판정(classify_tense) : 같은 계열.
셋을 각각 땜질하면 다음 자리에서 또 만난다.

`parse_obj` - 객체 하나를 받는 자리.
  1층 코드펜스 제거 후 파싱 / 2층 첫 균형 잡힌 {...} 블록만 떼어 파싱 /
  3층 `salvage_keys`에 따라 키별 정규식으로 값만 건지기.
  셋 다 실패하면 `LLMJsonError`를 올린다. **조용히 빈 dict를 돌려주지 않는다** -
  호출부가 실패 건수를 세고 있다.

`parse_list` - 배열을 받는 자리. `weekly-vibe/scripts/vibe_search.py`의
  `_parse_json_robust`가 원본이다(1차 원본 → 2차 수리 → 3차 개별 객체 추출).
  전부 실패하면 원본과 같이 빈 리스트를 돌려준다.

import 시점에 stdout을 재래핑하거나 `logging.basicConfig`를 부르지 않는다 -
레이더의 `app.py`·`classify_tense.py`가 서버 프로세스 안에서 이 모듈을 import한다.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

__all__ = ["LLMJsonError", "parse_obj", "parse_list"]


class LLMJsonError(ValueError):
    """3층 방어가 모두 실패했다."""


# ── 전처리 ────────────────────────────────────────────────


def _strip_fence(raw: str) -> str:
    """코드펜스(```json ... ```)를 벗긴다. 펜스가 없으면 그대로 돌려준다."""
    s = (raw or "").strip()
    if "```" not in s:
        return s
    parts = s.split("```")
    body = (parts[1] if len(parts) > 1 else s).lstrip()
    # 펜스 첫 줄의 언어 태그(json 등)를 벗긴다. 본문이 바로 시작하면 건드리지 않는다.
    if body[:1] not in ("{", "["):
        body = re.sub(r"^[A-Za-z0-9_+.-]{1,12}[ \t]*(\r?\n|(?=[\{\[]))", "", body)
    return body.strip()


def _first_json_block(raw: str, opener: str = "{") -> str:
    """첫 균형 잡힌 {...}(또는 [...]) 블록만 떼어낸다.

    모델이 JSON 뒤에 설명을 붙이면 json.loads가 「Extra data」로 깨진다.
    중괄호 깊이를 세되 문자열 안과 이스케이프는 건너뛴다.
    """
    closer = "}" if opener == "{" else "]"
    start = raw.find(opener)
    if start < 0:
        return ""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return raw[start:]


def _coerce_obj(data):
    """dict를 꺼낸다. 모델이 객체 하나를 배열로 감싸 보내는 엣지를 흡수한다."""
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        for x in data:
            if isinstance(x, dict):
                return x
    return None


# ── 3층: 키별 구조 ────────────────────────────────────────


def _salvage(raw: str, salvage_keys: dict) -> dict:
    """통짜 파싱이 깨졌을 때 키별 정규식으로 값만 건진다.

    `salvage_keys` = {"필드명": "bool" | "str" | "enum"}.
      bool : true|false
      enum : 따옴표 안 값(값에 따옴표가 없다고 본다)
      str  : 값 안에 따옴표가 있을 수 있어 다음 키나 닫는 중괄호까지 넉넉히 잡는다
    """
    out: dict = {}
    for key, kind in (salvage_keys or {}).items():
        k = re.escape(key)
        kind = (kind or "str").lower()
        if kind == "bool":
            m = re.search(r'"%s"\s*:\s*(true|false)' % k, raw, re.I)
            if m:
                out[key] = m.group(1).lower() == "true"
            continue
        if kind == "enum":
            m = re.search(r'"%s"\s*:\s*"([^"]*)"' % k, raw)
            if m:
                out[key] = m.group(1).strip()
            continue
        # str - 닫는 따옴표 뒤에 다음 키나 중괄호가 오는 자리까지 non-greedy로 민다
        m = re.search(r'"%s"\s*:\s*"(.*?)"\s*(?:,\s*"|\}|$)' % k, raw, re.S)
        if not m:
            m = re.search(r'"%s"\s*:\s*"(.*)"' % k, raw, re.S)
        if m:
            out[key] = m.group(1).replace('\\"', '"').replace("\\n", "\n").strip()
    return out


# ── 공개 API ──────────────────────────────────────────────


def parse_obj(raw: str, salvage_keys: dict | None = None) -> dict:
    """LLM 응답에서 JSON 객체 하나를 꺼낸다. 실패하면 LLMJsonError."""
    if not isinstance(raw, str) or not raw.strip():
        raise LLMJsonError("빈 응답")

    text = _strip_fence(raw)

    # 1층 - 통짜
    try:
        obj = _coerce_obj(json.loads(text))
    except json.JSONDecodeError as exc:
        log.debug("통짜 파싱 실패(1층): %s", exc)
    else:
        if obj is not None:
            return obj

    # 2층 - 첫 균형 블록만
    block = _first_json_block(text)
    if block:
        try:
            obj = _coerce_obj(json.loads(block))
        except json.JSONDecodeError as exc:
            log.debug("블록 파싱 실패(2층): %s", exc)
        else:
            if obj is not None:
                log.info("첫 {...} 블록만 떼어 파싱 성공(2층)")
                return obj

    # 3층 - 키별로 건지기
    if salvage_keys:
        out = _salvage(text, salvage_keys)
        if out:
            log.warning("통짜 파싱 실패 - 키 %d개만 건짐(3층): %s",
                        len(out), ", ".join(out))
            return out

    raise LLMJsonError("JSON 파싱 실패: %s" % text[:300])


def parse_list(raw: str) -> list:
    """LLM 응답에서 JSON 배열을 꺼낸다. 실패 시 수리 → 개별 객체 추출 폴백.

    `vibe_search.py`의 `_parse_json_robust`가 원본이고 3단 순서를 그대로 지킨다.
    앞에 코드펜스 제거만 얹었다(원본은 호출부가 먼저 벗겼다).
    전부 실패하면 원본과 같이 빈 리스트.
    """
    text = _strip_fence(raw or "")

    # 1차: 원본 그대로
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data] if isinstance(data, dict) else data
    except json.JSONDecodeError as exc:
        log.warning("JSON 디코드 실패 (1차): %s", exc)

    # 2차: 간단한 수리
    repaired = re.sub(r",\s*([}\]])", r"\1", text)       # trailing comma
    repaired = re.sub(r"[\x00-\x1f]", " ", repaired)     # control chars
    repaired = repaired.replace("\\'", "'")
    try:
        data = json.loads(repaired)
        return data if isinstance(data, list) else [data] if isinstance(data, dict) else data
    except json.JSONDecodeError:
        log.warning("JSON 수리 실패 (2차)")

    # 3차: 개별 JSON 객체를 하나씩 추출
    results = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start:i + 1]
                try:
                    obj = json.loads(fragment)
                    results.append(obj)
                except json.JSONDecodeError:
                    # 개별 객체도 수리 시도
                    frag2 = re.sub(r",\s*}", "}", fragment)
                    frag2 = re.sub(r"[\x00-\x1f]", " ", frag2)
                    try:
                        obj = json.loads(frag2)
                        results.append(obj)
                    except json.JSONDecodeError:
                        log.warning("개별 객체 파싱 실패: %s", fragment[:120])
                start = None
    if results:
        log.info("개별 객체 추출 성공: %d건", len(results))
    else:
        log.warning("모든 파싱 실패, 원문 500자: %s", text[:500])
    return results
