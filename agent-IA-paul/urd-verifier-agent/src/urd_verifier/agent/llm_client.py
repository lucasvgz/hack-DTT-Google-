"""Unified LLM & Multimodal Vision client with OpenAI, Gemini, Anthropic, and offline mode."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from urd_verifier.config import VerifierSettings


def _extract_json_block(text: str) -> Any:
    """Extract JSON array/object from LLM response text."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class LLMClient:
    """Abstracts text & vision calls across Gemini, OpenAI, Anthropic, or offline fallback."""

    def __init__(self, settings: VerifierSettings) -> None:
        self.settings = settings
        self.provider = settings.resolve_active_provider()

    @property
    def is_online(self) -> bool:
        return self.provider != "offline"

    def analyze_json(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str] | None = None,
    ) -> Any:
        """Ask the configured LLM (optionally with images for Vision) to return structured JSON."""
        if not self.is_online:
            return None

        try:
            if self.provider == "vertexai":
                return self._call_vertexai(system_prompt, user_prompt, image_paths)
            if self.provider == "gemini":
                return self._call_gemini(system_prompt, user_prompt, image_paths)
            if self.provider == "openai":
                return self._call_openai(system_prompt, user_prompt, image_paths)
            if self.provider == "anthropic":
                return self._call_anthropic(system_prompt, user_prompt, image_paths)
        except Exception:
            # Never crash verification pipeline if external API fails/times out
            return None
        return None

    def _call_vertexai(
        self, system_prompt: str, user_prompt: str, image_paths: list[str] | None
    ) -> Any:
        from google import genai
        from google.genai import types

        client = genai.Client(
            vertexai=True,
            project=self.settings.vertex_project,
            location=self.settings.vertex_location,
        )
        model = self.settings.llm_model or "gemini-2.5-flash"
        contents: list[Any] = [user_prompt]
        for img_path in image_paths or []:
            p = Path(img_path)
            if p.exists():
                contents.append(
                    types.Part.from_bytes(data=p.read_bytes(), mime_type="image/png")
                )
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        return _extract_json_block(resp.text or "")

    def _call_gemini(
        self, system_prompt: str, user_prompt: str, image_paths: list[str] | None
    ) -> Any:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.settings.gemini_api_key)
        model = self.settings.llm_model or "gemini-2.5-flash"
        contents: list[Any] = [user_prompt]
        for img_path in image_paths or []:
            p = Path(img_path)
            if p.exists():
                contents.append(
                    types.Part.from_bytes(data=p.read_bytes(), mime_type="image/png")
                )
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        return _extract_json_block(resp.text or "")

    def _call_openai(
        self, system_prompt: str, user_prompt: str, image_paths: list[str] | None
    ) -> Any:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.llm_model or "gpt-4o-mini"
        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for img_path in image_paths or []:
            p = Path(img_path)
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                )
        resp = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        text = resp.choices[0].message.content or ""
        return _extract_json_block(text)

    def _call_anthropic(
        self, system_prompt: str, user_prompt: str, image_paths: list[str] | None
    ) -> Any:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.settings.anthropic_api_key)
        model = self.settings.llm_model or "claude-3-5-sonnet-latest"
        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for img_path in image_paths or []:
            p = Path(img_path)
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                user_content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    }
                )
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        return _extract_json_block(text)
