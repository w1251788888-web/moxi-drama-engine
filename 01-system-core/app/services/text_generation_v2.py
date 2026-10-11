"""
文本生成服务 v2 - 支持多模型灵活调用
支持：OpenAI、Claude、Anthropic SDK、自定义API
"""

import os
import json
import asyncio
from typing import Optional, AsyncGenerator, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

# 延迟导入，避免循环引用
def _ssl_verify() -> bool:
    try:
        from app.services.text_generation_service import get_ssl_verify
        return get_ssl_verify()
    except Exception:
        return True


@dataclass
class GenerationResult:
    """生成结果"""
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    finish_reason: str = ""
    raw_response: Optional[dict] = None


class ModelProviderClient:
    """模型提供商客户端基类"""

    def __init__(self, base_url: str, api_key: str, default_model: str = "", provider_type: str = ""):
        # 去掉末尾斜杠和多余的 /v1，避免拼接时出现 /v1/v1/chat/completions
        stripped = base_url.rstrip("/")
        self.base_url = stripped[:-3] if stripped.endswith("/v1") else stripped
        self.api_key = api_key
        self.default_model = default_model
        self.provider_type = str(provider_type or "").strip().lower()
        self.client = httpx.AsyncClient(timeout=300.0, verify=_ssl_verify())

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        stream: bool = False,
        **kwargs
    ) -> GenerationResult:
        raise NotImplementedError

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError

    async def close(self):
        await self.client.aclose()


class OpenAICompatibleClient(ModelProviderClient):
    """OpenAI兼容API客户端（支持大多数国产API）"""

    def _chat_completions_url(self) -> str:
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        if self.provider_type == "deepseek" and host.endswith("deepseek.com"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    @staticmethod
    def _apply_model_compat_payload(payload: dict[str, Any]) -> dict[str, Any]:
        model = str(payload.get("model") or "").strip().lower()
        if not (model.startswith("kimi-k2.5") or model.startswith("kimi-k2.6")):
            return payload

        adjusted = dict(payload)
        thinking = adjusted.get("thinking")
        if not isinstance(thinking, dict):
            thinking = {"type": "disabled"}
            adjusted["thinking"] = thinking

        thinking_type = str(thinking.get("type") or "").strip().lower()
        adjusted["temperature"] = 0.6 if thinking_type == "disabled" else 1.0
        return adjusted

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        stream: bool = False,
        response_format: Optional[dict] = None,
        **kwargs
    ) -> GenerationResult:
        """使用OpenAI兼容API生成文本"""

        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        payload = self._apply_model_compat_payload(payload)

        if response_format:
            payload["response_format"] = response_format

        # 添加额外参数
        for key, value in kwargs.items():
            if key not in payload:
                payload[key] = value

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            response = await self.client.post(
                self._chat_completions_url(),
                json=payload,
                headers=headers
            )
            response.raise_for_status()

            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")

            # 解析usage
            usage = data.get("usage", {})

            return GenerationResult(
                content=content,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                model=data.get("model", model),
                finish_reason=choice.get("finish_reason", ""),
                raw_response=data
            )

        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"模型API错误: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""

        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        payload = self._apply_model_compat_payload(payload)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with self.client.stream(
                "POST",
                self._chat_completions_url(),
                json=payload,
                headers=headers
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue

                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except:
                            continue

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"流式生成失败: {str(e)}")


class AnthropicClient(ModelProviderClient):
    """Anthropic Claude API客户端"""

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> GenerationResult:
        """使用Anthropic API生成文本"""

        model = model or self.default_model or "claude-3-5-sonnet-20241022"

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = await self.client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=headers
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("content", [{}])[0].get("text", "")

            return GenerationResult(
                content=content,
                prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                total_tokens=data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0),
                model=model,
                finish_reason=data.get("stop_reason", ""),
                raw_response=data
            )

        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Anthropic API错误: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""

        model = model or self.default_model or "claude-3-5-sonnet-20241022"

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=headers
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    yield text
                        except:
                            continue

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"流式生成失败: {str(e)}")


class GenerationService:
    """生成服务管理器"""

    _instance = None
    _clients: Dict[str, ModelProviderClient] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_client(self, provider_type: str, base_url: str, api_key: str, default_model: str = "") -> ModelProviderClient:
        """获取或创建客户端"""

        cache_key = f"{provider_type}:{base_url}:{api_key[:8]}"

        if cache_key not in self._clients:
            if provider_type == "anthropic":
                client = AnthropicClient(base_url, api_key, default_model, provider_type)
            else:
                # 默认使用OpenAI兼容格式
                client = OpenAICompatibleClient(base_url, api_key, default_model, provider_type)

            self._clients[cache_key] = client

        return self._clients[cache_key]

    async def generate(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> GenerationResult:
        """生成文本"""

        client = self.get_client(provider, base_url, api_key, model)
        return await client.generate(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    async def generate_stream(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""

        client = self.get_client(provider, base_url, api_key, model)
        async for chunk in client.generate_stream(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ):
            yield chunk

    async def close_all(self):
        """关闭所有客户端"""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()


# 全局服务实例
generation_service = GenerationService()


# 便捷函数
async def generate_text(
    provider: str = "openai",
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4000,
    response_format: Optional[dict] = None,
    **kwargs
) -> GenerationResult:
    """
    便捷的文本生成函数

    示例:
        result = await generate_text(
            provider="openai",
            base_url="https://api.openai.com",
            api_key="sk-...",
            model="gpt-4",
            prompt="写一段短剧剧本"
        )
    """
    return await generation_service.generate(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        **kwargs
    )


def _repair_json_like_v2(text: str) -> str:
    """修复 LLM 常见 JSON 格式问题：中文引号、尾逗号、未加引号的键名。"""
    import re
    repaired = text.strip()
    # 去除 markdown 代码块标记
    if repaired.startswith("```"):
        repaired = repaired.split("\n", 1)[1] if "\n" in repaired else ""
        if repaired.endswith("```"):
            repaired = repaired[:-3]
        repaired = repaired.strip()
    # 中文引号替换为英文引号
    repaired = repaired.replace(""", '"').replace(""", '"').replace("'", "'").replace("'", "'")
    # 去除尾逗号：{"a":1,} / [1,2,]
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    # 为常见未加引号的键名补引号
    pattern = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)')
    repaired = pattern.sub(r'\1"\2"\3', repaired)
    return repaired


def _extract_first_json_object_v2(content: str) -> dict:
    cleaned = _repair_json_like_v2(content)
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in ("{", "["):
            continue
        try:
            parsed, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed:
            first_obj = next((item for item in parsed if isinstance(item, dict)), None)
            if first_obj:
                return first_obj
    raise ValueError("无法从文本中提取合法 JSON 对象")


async def generate_json(
    provider: str = "openai",
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.7,
    **kwargs
) -> dict:
    """生成JSON格式输出"""

    result = await generate_text(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        response_format={"type": "json_object"},
        **kwargs
    )

    try:
        parsed = json.loads(result.content)
    except json.JSONDecodeError:
        try:
            parsed = _extract_first_json_object_v2(result.content)
        except ValueError:
            raise HTTPException(status_code=500, detail="无法解析JSON输出")

    if isinstance(parsed, list):
        parsed = {"items": parsed}
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=500, detail="无法解析JSON输出")
    return parsed


async def generate_stream_text(
    provider: str = "openai",
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    prompt: str = "",
    **kwargs
) -> AsyncGenerator[str, None]:
    """流式生成文本"""

    async for chunk in generation_service.generate_stream(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
        **kwargs
    ):
        yield chunk
