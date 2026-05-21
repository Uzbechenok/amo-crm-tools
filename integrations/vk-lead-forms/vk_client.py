"""
VK Lead Forms API Client.

Получение списка лид-форм и лидов из VK Community.
Документация: https://dev.vk.com/method/leadForms
"""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class VkClient:
    """Клиент для работы с VK Lead Forms API."""

    BASE_URL = "https://api.vk.com/method"
    API_VERSION = "5.199"

    def __init__(self, token: str, group_id: int) -> None:
        """
        Инициализация VK клиента.

        Args:
            token: VK Group Token (токен сообщества).
            group_id: ID сообщества VK (числовой).
        """
        self.token = token
        self.group_id = group_id

    def _call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Вызов VK API метода.

        Args:
            method: Название метода (например, 'leadForms.getLeads').
            params: Параметры запроса.

        Returns:
            Ответ API.

        Raises:
            requests.RequestException: При ошибке сети/HTTP.
            ValueError: При ошибке VK API.
        """
        payload = {
            "access_token": self.token,
            "v": self.API_VERSION,
            **(params or {}),
        }

        safe_payload = {k: v if k != 'access_token' else '***' for k, v in payload.items()}
        logger.debug("VK API call: %s with params=%s", method, safe_payload)
        response = requests.post(f"{self.BASE_URL}/{method}", data=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Проверка ошибок VK API
        if "error" in data:
            error_msg = data["error"].get("error_msg", "Unknown VK API error")
            error_code = data["error"].get("error_code", 0)
            raise ValueError(f"VK API error [{error_code}]: {error_msg}")

        return data.get("response", {})

    def get_lead_forms(self) -> List[Dict[str, Any]]:
        """
        Получение списка всех лид-форм сообщества.

        Returns:
            Список лид-форм группы.
        """
        result = self._call("leadForms.get", {"group_id": self.group_id})
        forms = result if isinstance(result, list) else result.get("items", [])
        logger.info("Получено лид-форм: %d", len(forms))
        return forms

    def get_leads(self, form_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получение лидов конкретной формы.

        Args:
            form_id: ID лид-формы.
            limit: Максимальное количество лидов (макс. 100 за запрос).

        Returns:
            Список лидов.
        """
        result = self._call("leadForms.getLeads", {
            "group_id": self.group_id,
            "form_id": form_id,
            "limit": limit,
        })
        leads = result if isinstance(result, list) else result.get("leads", [])
        logger.info("Получено лидов для формы %d: %d", form_id, len(leads))
        return leads

    @staticmethod
    def parse_answers(lead: Dict[str, Any]) -> Dict[str, str]:
        """
        Парсинг answers лида в плоскую структуру {вопрос: ответ}.

        Ответы VK приходят в виде списка словарей вида:
        [
            {"question_key": "Имя", "answer": "Иван"},
            {"question_key": "Телефон", "answer": "+7...", "key": "phone"},
            ...
        ]

        Args:
            lead: Данные лида (словарь, содержащий 'answers').

        Returns:
            Словарь {название_вопроса: ответ}.
        """
        answers = lead.get("answers", [])
        result: Dict[str, str] = {}

        for item in answers:
            # question_key — отображаемое название поля формы
            question = item.get("question_key", "")
            answer = item.get("answer", "")

            # Пропускаем пустые ответы
            if not question or not answer:
                continue

            # Если у вопроса есть key (email, phone и т.д.), используем question_key как имя
            result[question] = answer

        return result

    @staticmethod
    def flatten_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразование полного лида VK в плоскую структуру.

        Извлекает основные поля лида и парсит answers.

        Args:
            lead: Исходные данные лида от VK API.

        Returns:
            Плоский словарь с полями: lead_id, form_id, user_id, date,
            и все распарсенные ответы.
        """
        flat = {
            "lead_id": lead.get("lead_id") or lead.get("id"),
            "form_id": lead.get("form_id"),
            "user_id": lead.get("user_id"),
            "date": lead.get("date"),
            "ad_id": lead.get("ad_id"),
        }

        # Парсим ответы
        answers = VkClient.parse_answers(lead)
        flat.update(answers)

        return flat
