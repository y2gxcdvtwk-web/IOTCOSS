import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.models import AnalysisResult


class Analyzer:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def analyze(self, text: str) -> AnalysisResult:
        if self.settings.ai_provider.lower() == "openai" and self.settings.openai_api_key:
            return await self._openai(text)
        return self._local(text)

    def _local(self, text: str) -> AnalysisResult:
        clean = re.sub(r"\s+", " ", text).strip()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", clean) if s.strip()]
        urgent = any(word in clean.lower() for word in ("자해", "극단", "suicide", "self-harm", "응급"))
        strained = any(word in clean.lower() for word in ("불안", "우울", "실패", "못하", "anxious", "depressed"))
        risk = "high" if urgent else "medium" if strained else "low"
        summary = " ".join(sentences[:2])[:500] or "분석할 텍스트가 없습니다."
        insights = [
            f"입력 분량은 약 {len(clean)}자입니다.",
            f"핵심 문장 {min(len(sentences), 2)}개를 중심으로 요약했습니다.",
        ]
        recommendations = ["다음 행동을 10분 이내의 작은 단위로 정하고 완료 여부를 기록하세요."]
        if risk == "medium":
            recommendations.append("부담이 지속되면 신뢰하는 사람이나 전문가와 현재 상태를 공유하세요.")
        if risk == "high":
            recommendations = ["즉각적인 위험이 있다면 지역 응급 서비스 또는 가까운 의료기관에 연락하세요."]
        return AnalysisResult(
            provider="local", model="rule-based-v1", summary=summary,
            insights=insights, recommendations=recommendations, risk_level=risk,
        )

    async def _openai(self, text: str) -> AnalysisResult:
        schema_hint = {
            "summary": "string", "insights": ["string"], "recommendations": ["string"],
            "risk_level": "low|medium|high",
        }
        prompt = (
            "사용자의 기록을 분석하되 진단하지 마세요. 실행 가능한 조언을 제시하고, "
            f"반드시 다음 JSON 구조로만 답하세요: {json.dumps(schema_hint, ensure_ascii=False)}\n\n{text}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.ai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            raw = response.json()
        data = json.loads(raw["choices"][0]["message"]["content"])
        return AnalysisResult(
            provider="openai", model=self.settings.ai_model, raw={"id": raw.get("id")},
            **data,
        )

