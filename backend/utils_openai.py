from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class OpenAIWrapper:
    def __init__(self) -> None:
        api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("openai_api_key") or "").strip()
        if not api_key:
            raise RuntimeError(
                "OpenAI API key is missing. Set OPENAI_API_KEY (or openai_api_key) in environment variables."
            )

        self.chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip()
        self.vision_model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()
        self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large").strip()
        self.client = OpenAI(api_key=api_key)

    def _parse_json_response(self, content: str) -> Any:
        text = (content or "").strip()
        if not text:
            return {}

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            return json.loads(text)
        except Exception:
            pass

        for left, right in [("{", "}"), ("[", "]")]:
            start = text.find(left)
            end = text.rfind(right)
            if start >= 0 and end > start:
                snippet = text[start : end + 1]
                try:
                    return json.loads(snippet)
                except Exception:
                    continue

        raise ValueError("OpenAI JSON 응답 파싱 실패")

    def _chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        temperature: float = 0,
        max_tokens: int | None = None,
        retries: int = 2,
    ) -> Any:
        last_error: Exception | None = None
        for _ in range(retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "temperature": temperature,
                    "response_format": response_format,
                    "messages": messages,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                return self._parse_json_response(content)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"OpenAI JSON 응답 생성 실패: {last_error}") from last_error

    def embed_texts(self, texts: list[str], batch_size: int = 96) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self.client.embeddings.create(model=self.embedding_model, input=batch)
            vectors.extend(item.embedding for item in response.data)
        return vectors

    def transcribe_equations(self, image_path: Path) -> list[dict[str, Any]]:
        image_bytes = image_path.read_bytes()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        image_uri = f"data:image/png;base64,{b64}"
        schema = {
            "name": "equation_transcription",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "equations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "latex": {"type": "string"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": ["latex", "confidence"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["equations"],
                "additionalProperties": False,
            },
        }

        system_prompt = (
            "You are an OCR transcriber for mathematical equations only. "
            "Do not summarize. Do not explain. Return equations exactly as LaTeX."
        )
        user_prompt = (
            "Transcribe only equations from this page image. "
            "Ignore prose text. Return JSON only. "
            "If uncertain about a symbol, still transcribe and reduce confidence."
        )

        try:
            payload = self._chat_json(
                model=self.vision_model,
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_schema", "json_schema": schema},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": image_uri}},
                        ],
                    },
                ],
            )
        except Exception:
            payload = self._chat_json(
                model=self.vision_model,
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": image_uri}},
                        ],
                    },
                ],
            )

        equations_raw: Any = []
        if isinstance(payload, dict):
            equations_raw = payload.get("equations", [])
        elif isinstance(payload, list):
            equations_raw = payload
        elif isinstance(payload, str):
            equations_raw = [payload]

        if isinstance(equations_raw, dict):
            equations = [equations_raw]
        elif isinstance(equations_raw, list):
            equations = equations_raw
        elif isinstance(equations_raw, str):
            equations = [equations_raw]
        else:
            equations = []

        clean: list[dict[str, Any]] = []
        for item in equations:
            if isinstance(item, dict):
                latex = str(item.get("latex", "")).strip()
                confidence_raw = item.get("confidence", 0.0)
            elif isinstance(item, str):
                latex = item.strip()
                confidence_raw = 0.0
            else:
                continue
            if not latex:
                continue
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = min(1.0, max(0.0, confidence))
            clean.append({"latex": latex, "confidence": confidence})
        return clean

    def answer_with_citations(self, question: str, context: str, force_attempt: bool = False) -> dict[str, Any]:
        schema = {
            "name": "qa_with_citations",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"ref_no": {"type": "integer", "minimum": 1}},
                            "required": ["ref_no"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["answer", "citations"],
                "additionalProperties": False,
            },
        }

        system_prompt = (
            "너는 논문 QA 보조자다. 제공된 컨텍스트만 사용한다. "
            "관련 근거가 전혀 없을 때만 정확히 '근거 부족'이라고 답한다. "
            "관련 근거가 있으면 간결하게 답하고 최소 2개 ref_no를 citations에 넣어라. "
            "수식 기호가 깨져 보여도 문맥상 근거가 있으면 활용하라. "
            "답변은 반드시 한국어로 작성하라."
        )
        if force_attempt:
            system_prompt += " 가능한 한 근거를 찾아 답변을 시도하라."
        user_prompt = (
            "질문:\n"
            f"{question}\n\n"
            "컨텍스트(ref 번호 기반):\n"
            f"{context}\n\n"
            "JSON만 반환. citations에는 ref_no만 넣어라."
        )
        payload = self._chat_json(
            model=self.chat_model,
            temperature=0,
            max_tokens=1500,
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if not isinstance(payload, dict):
            raise RuntimeError("QA 응답 형식이 잘못되었습니다.")
        return payload

    def summarize_paper(self, title: str, paper_text: str, equations: str) -> dict[str, Any]:
        schema = {
            "name": "paper_summary",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["ko"]},
                    "one_sentence": {"type": "string"},
                    "problem": {"type": "string"},
                    "key_idea": {"type": "array", "items": {"type": "string"}},
                    "method": {
                        "type": "object",
                        "properties": {
                            "inputs": {"type": "array", "items": {"type": "string"}},
                            "model": {"type": "string"},
                            "training_objective": {"type": "string"},
                        },
                        "required": ["inputs", "model", "training_objective"],
                        "additionalProperties": False,
                    },
                    "math_core": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "latex": {"type": "string"},
                                "meaning": {"type": "string"},
                            },
                            "required": ["name", "latex", "meaning"],
                            "additionalProperties": False,
                        },
                    },
                    "limitations": {"type": "array", "items": {"type": "string"}},
                    "repro_checklist": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "language",
                    "one_sentence",
                    "problem",
                    "key_idea",
                    "method",
                    "math_core",
                    "limitations",
                    "repro_checklist",
                ],
                "additionalProperties": False,
            },
        }

        system_prompt = (
            "당신은 논문 구조화 요약기다. "
            "JSON 스키마를 엄격히 지켜라. "
            "모든 설명 텍스트 필드는 반드시 한국어로 작성하라. "
            "language 필드는 반드시 'ko'로 반환하라."
        )
        user_prompt = (
            "논문 제목:\n"
            f"{title}\n\n"
            "논문 본문 발췌:\n"
            f"{paper_text}\n\n"
            "추출된 수식(LaTeX):\n"
            f"{equations}\n\n"
            "마크다운 금지. JSON만 출력."
        )
        payload = self._chat_json(
            model=self.chat_model,
            temperature=0,
            max_tokens=2200,
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if not isinstance(payload, dict):
            raise RuntimeError("요약 응답 형식이 잘못되었습니다.")
        return payload

    def translate_query_to_english(self, question: str) -> str:
        schema = {
            "name": "query_translation",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "query_en": {"type": "string"},
                },
                "required": ["query_en"],
                "additionalProperties": False,
            },
        }
        payload = self._chat_json(
            model=self.chat_model,
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {
                    "role": "system",
                    "content": "Translate search queries into concise academic English for paper retrieval.",
                },
                {
                    "role": "user",
                    "content": f"Query: {question}\nReturn JSON only.",
                },
            ],
            retries=1,
        )
        if not isinstance(payload, dict):
            return question
        query_en = str(payload.get("query_en", "")).strip()
        return query_en or question

    def answer_best_effort(self, question: str, context: str) -> str:
        schema = {
            "name": "qa_best_effort",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        }
        payload = self._chat_json(
            model=self.chat_model,
            temperature=0,
            max_tokens=700,
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "제공된 컨텍스트만 사용해서 한국어로 간결히 답하라. "
                        "컨텍스트에 단서가 있으면 반드시 답변을 시도하고, 불확실한 부분만 제한적으로 명시하라. "
                        "'근거 부족' 같은 거절형 문구는 컨텍스트가 완전히 비어 있을 때만 사용하라."
                    ),
                },
                {
                    "role": "user",
                    "content": f"질문:\n{question}\n\n컨텍스트:\n{context}\n\nJSON만 출력.",
                },
            ],
            retries=1,
        )
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("answer", "")).strip()
