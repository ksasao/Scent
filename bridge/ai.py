import aiohttp
import json
import logging
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OPENAI_API_KEY
from events import Event, EventType

logger = logging.getLogger(__name__)

class OllamaClient:
    """Ollama ローカル LLM クライアント"""
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url
        self.model = model
        self.is_available = False

    async def check_health(self) -> bool:
        """Ollama サーバーの稼働確認"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    self.is_available = resp.status == 200
                    return self.is_available
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            self.is_available = False
            return False

    async def analyze_event(self, event: Event) -> str:
        """イベントを分析して AI に委ねる"""
        if not self.is_available:
            return "Ollama is not available"

        prompt = f"""You are a sensor data analysis agent. Analyze the following event and provide a brief response in Japanese.

Event type: {event.type.value}
Timestamp: {event.timestamp}
Data: {json.dumps(event.data, ensure_ascii=False, indent=2)}

Provide:
1. Brief description of what happened
2. Any anomalies or concerns
3. Recommended next action (if any)
"""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("response", "No response")
                    else:
                        logger.error(f"Ollama error: {resp.status}")
                        return f"Error: {resp.status}"
        except Exception as e:
            logger.error(f"Ollama analyze failed: {e}")
            return f"Error: {str(e)}"

class AIRouter:
    """AI エンドポイントのルーター"""
    def __init__(self):
        self.ollama = OllamaClient()
        self.openai_available = bool(OPENAI_API_KEY)

    async def route_event(self, event: Event) -> dict:
        """イベントを適切な AI に振り分ける"""
        result = {
            "event_id": event.id,
            "type": event.type.value,
            "ai_response": None,
            "ai_used": None,
        }

        # 軽いイベント → Ollama
        if event.type in [EventType.CRC_ERROR, EventType.DATA_RECORD]:
            if self.ollama.is_available:
                result["ai_response"] = await self.ollama.analyze_event(event)
                result["ai_used"] = "ollama"
            else:
                result["ai_response"] = "Local AI unavailable, event logged"
                result["ai_used"] = "none"

        # 重いイベント → Ollama (for now)
        # 実装予定: OpenAI / Claude へのルーティング
        elif event.type in [EventType.SESSION_ENDED, EventType.SENSOR_ANOMALY]:
            if self.ollama.is_available:
                result["ai_response"] = await self.ollama.analyze_event(event)
                result["ai_used"] = "ollama"
            else:
                result["ai_response"] = "Analysis deferred"
                result["ai_used"] = "none"

        # その他
        else:
            result["ai_response"] = f"Event logged: {event.type.value}"
            result["ai_used"] = "logging"

        return result
