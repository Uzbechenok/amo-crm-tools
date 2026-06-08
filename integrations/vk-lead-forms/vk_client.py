"""
VK Ads API Client — Lead Forms.

Получение списка лид-форм и лидов через VK Ads API (ads.vk.com).
Документация: https://ads.vk.com/en/doc/api/resource/LeadForms
Авторизация: https://ads.vk.com/en/doc/api/info/Authorization
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


class VkClient:
    """Клиент для работы с VK Ads Lead Forms API.

    Заменяет старый клиент на базе dev.vk.com/method/leadForms.
    Авторизация через OAuth2 Client Credentials Grant.
    """

    BASE_URL = "https://ads.vk.com/api"
    AUTH_URL = "https://ads.vk.com/api/v2/oauth2/token.json"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        ad_account_id: int,
        state_file: str = DEFAULT_STATE_FILE,
    ) -> None:
        """
        Args:
            client_id: ID приложения из VK Ads → Настройки → API Access.
            client_secret: Секретный ключ (заглушка до получения от клиента).
            ad_account_id: ID рекламного кабинета VK.
            state_file: Путь к state.json для хранения токенов.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.ad_account_id = ad_account_id
        self.state_file = state_file

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._load_tokens()

    # ─────────────── OAuth2 ───────────────

    def _load_tokens(self) -> None:
        """Загрузка токенов из state.json (секция vk_token)."""
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            token_data = data.get("vk_token", {})
            self._access_token = token_data.get("access_token")
            self._refresh_token = token_data.get("refresh_token")
            self._expires_at = token_data.get("expires_at", 0.0)
            if self._access_token:
                logger.info("VK Ads токены загружены из %s", self.state_file)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Файл токенов не найден: %s", self.state_file)

    def _save_tokens(self) -> None:
        """Сохранение токенов в state.json."""
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        data["vk_token"] = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
        }
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("VK Ads токены сохранены в %s", self.state_file)

    def _is_token_expired(self) -> bool:
        """Проверка, истёк ли токен (запас 60 секунд)."""
        return time.time() >= (self._expires_at - 60)

    def fetch_token(self) -> None:
        """Первичное получение токена через Client Credentials Grant.

        Вызывается один раз при первом запуске.
        """
        if not self.client_secret:
            raise RuntimeError(
                "client_secret не заполнен. Попросите клиента скопировать его "
                "из ads.vk.com → Настройки → API Access."
            )

        response = requests.post(
            self.AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", "")
        self._expires_at = time.time() + int(data.get("expires_in", 86400))
        self._save_tokens()
        logger.info("VK Ads токен получен")

    def _refresh_token_request(self) -> None:
        """Обновление access_token через refresh_token."""
        if not self._refresh_token:
            raise RuntimeError(
                "Нет refresh_token. Выполните fetch_token() для первичной авторизации."
            )

        response = requests.post(
            self.AUTH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 86400))
        self._save_tokens()
        logger.info("VK Ads токен обновлён")

    def _ensure_token(self) -> str:
        """Проверка токена: если истёк — обновить, если нет — вернуть.

        Returns:
            Актуальный access_token.
        """
        if not self._access_token:
            self.fetch_token()
        elif self._is_token_expired():
            logger.info("VK Ads токен истёк, выполняю refresh...")
            self._refresh_token_request()
        return self._access_token  # type: ignore[return-value]

    # ─────────────── HTTP ───────────────

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET запрос к VK Ads API.

        Args:
            path: Путь, например /api/v1/lead_ads/lead_forms.json.
            params: Query-параметры.

        Returns:
            Распарсенный JSON ответ.
        """
        token = self._ensure_token()
        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    # ─────────────── Lead Forms ───────────────

    def get_lead_forms(self) -> List[Dict[str, Any]]:
        """Получение списка всех лид-форм рекламного кабинета.

        Returns:
            Список лид-форм (каждая — словарь с полями из LeadFormsListElement).
        """
        result = self._get("/v1/lead_ads/lead_forms.json")
        items = result.get("items", [])
        logger.info("Получено лид-форм: %d", len(items))
        return items

    def get_leads(
        self,
        form_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Получение лидов конкретной формы.

        Args:
            form_id: ID лид-формы.
            limit: Макс. количество лидов (макс. 50).
            offset: Смещение для пагинации.

        Returns:
            Список лидов (каждый — LeadsListElement).
        """
        params = {
            "_form_ids__in": str(form_id),
            "limit": min(limit, 50),
            "offset": offset,
        }
        result = self._get("/v1/lead_ads/leads.json", params=params)
        items = result.get("items", [])
        logger.info("Получено лидов для формы %s: %d", form_id, len(items))
        return items

    # ─────────────── Парсинг ───────────────

    @staticmethod
    def parse_answers(lead: Dict[str, Any]) -> Dict[str, str]:
        """Парсинг answers лида в плоскую структуру {вопрос: ответ}.

        VK Ads API возвращает ответы в виде:
            [{"question_text": "Имя", "answer_options": [...], "answer_text": "..."}, ...]

        Args:
            lead: Данные лида, содержащие ключ 'answers'.

        Returns:
            Словарь {название_вопроса: ответ}.
        """
        answers = lead.get("answers", [])
        if not answers:
            return {}

        result: Dict[str, str] = {}
        for item in answers:
            question = (item.get("question_text") or "").strip()
            if not question:
                continue

            # Приоритет: свободный текст > выбранный вариант > пропуск
            answer_text = (item.get("answer_text") or "").strip()
            if answer_text:
                result[question] = answer_text
                continue

            options = item.get("answer_options", [])
            if options:
                texts = [
                    opt.get("text", "").strip()
                    for opt in options
                    if opt.get("text")
                ]
                if texts:
                    result[question] = ", ".join(texts)

        return result

    @staticmethod
    def flatten_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
        """Преобразование лида VK Ads в плоскую структуру.

        Извлекает основные поля лида, контактные данные и answers.

        Args:
            lead: Исходный объект LeadsListElement из VK Ads API.

        Returns:
            Плоский словарь с базовыми полями и ответами.
        """
        flat: Dict[str, Any] = {
            "lead_id": lead.get("id"),
            "form_id": lead.get("form_id"),
        }

        # Дата создания — ISO строка, передаём как есть
        created_at = lead.get("created_at")
        if created_at:
            flat["date"] = created_at

        # Контактная информация
        contact_info = lead.get("contact_info") or {}
        if contact_info.get("first_name"):
            flat["contact_name"] = contact_info["first_name"]
        if contact_info.get("phone"):
            flat["contact_phone"] = contact_info["phone"]
        if contact_info.get("email"):
            flat["contact_email"] = contact_info["email"]
        if contact_info.get("social_media_profile"):
            flat["contact_social_media_profile"] = contact_info["social_media_profile"]

        # Ответы анкеты
        answers = VkClient.parse_answers(lead)
        flat.update(answers)

        return flat
