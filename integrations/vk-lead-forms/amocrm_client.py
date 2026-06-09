"""
amoCRM REST API v4 Client.

Аутентификация (OAuth2), поиск/создание контактов, создание сделок.
Документация: https://www.amocrm.ru/developers/content/api
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from state_utils import locked_update_state

logger = logging.getLogger(__name__)

# Путь к файлу состояния (токены, last_processed_lead_ids) по умолчанию
DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


@dataclass
class AmoAuth:
    """Данные OAuth2 аутентификации."""
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp


class AmoCRMClient:
    """Клиент для работы с amoCRM REST API v4."""

    def __init__(
        self,
        subdomain: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        state_file: str = DEFAULT_STATE_FILE,
    ) -> None:
        """
        Инициализация amoCRM клиента.

        Args:
            subdomain: Поддомен аккаунта (без .amocrm.ru).
            client_id: ID интеграции.
            client_secret: Секретный ключ интеграции.
            redirect_uri: Redirect URI приложения.
            state_file: Путь к файлу состояния для хранения токенов.
        """
        self.base_url = f"https://{subdomain}.amocrm.ru"
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.state_file = state_file

        self._auth: Optional[AmoAuth] = None
        self._load_auth()

    # ─────────────── OAuth2 ───────────────

    def _load_auth(self) -> None:
        """Загрузка токенов из state.json."""
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            token_data = data.get("token", {})
            self._auth = AmoAuth(
                access_token=token_data.get("access_token", ""),
                refresh_token=token_data.get("refresh_token", ""),
                expires_at=token_data.get("expires_at", 0),
            )
            logger.info("Токены загружены из %s", self.state_file)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            logger.warning("Файл токенов не найден или повреждён: %s", self.state_file)
            self._auth = None

    def _save_auth(self, auth: AmoAuth) -> None:
        """Сохранение токенов в state.json с файловой блокировкой."""
        def _update(data: dict) -> None:
            data["token"] = {
                "access_token": auth.access_token,
                "refresh_token": auth.refresh_token,
                "expires_at": auth.expires_at,
            }

        locked_update_state(self.state_file, _update)
        self._auth = auth
        logger.info("Токены сохранены в %s", self.state_file)

    def _is_token_expired(self) -> bool:
        """Проверка, истёк ли токен (с запасом в 60 секунд)."""
        if self._auth is None:
            return True
        return time.time() >= (self._auth.expires_at - 60)

    def authorize_from_code(self, auth_code: str) -> None:
        """
        Первичная авторизация по коду авторизации.

        Вызывается один раз для получения access/refresh токенов.

        Args:
            auth_code: Код авторизации из OAuth2 redirect.
        """
        url = f"{self.base_url}/oauth2/access_token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        auth = AmoAuth(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data["expires_in"],
        )
        self._save_auth(auth)
        logger.info("Успешная OAuth2 авторизация через код")

    def _refresh_token(self) -> None:
        """Обновление access token через refresh token."""
        if self._auth is None:
            raise RuntimeError("Нет токенов для обновления. Выполните authorize_from_code().")

        url = f"{self.base_url}/oauth2/access_token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self._auth.refresh_token,
            "redirect_uri": self.redirect_uri,
        }

        response = requests.post(url, json=payload, timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            if response.status_code in (400, 401):
                logger.error(
                    "Ошибка авторизации: требуется повторная авторизация. "
                    "Запустите: python3 main.py --auth-code <code>"
                )
            raise

        data = response.json()

        auth = AmoAuth(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data["expires_in"],
        )
        self._save_auth(auth)
        logger.info("Токен успешно обновлён")

    def _ensure_token(self) -> str:
        """
        Проверка и обновление токена при необходимости.

        Returns:
            Актуальный access token.
        """
        if self._is_token_expired():
            logger.info("Токен истёк, выполняю refresh...")
            self._refresh_token()
        return self._auth.access_token  # type: ignore[union-attr]

    # ─────────────── HTTP методы ───────────────

    def _headers(self) -> Dict[str, str]:
        """Формирование заголовков с Bearer токеном."""
        token = self._ensure_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        GET запрос к amoCRM API.

        Args:
            path: Путь (например, /api/v4/contacts).
            params: Query параметры.

        Returns:
            Ответ API, или пустой словарь, если тело пустое.
        """
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if response.status_code == 204 or not response.text.strip():
            return {}
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, data: Any) -> Dict[str, Any]:
        """
        POST запрос к amoCRM API.

        Args:
            path: Путь (например, /api/v4/contacts).
            data: Тело запроса.

        Returns:
            Ответ API.
        """
        url = f"{self.base_url}{path}"
        response = requests.post(url, headers=self._headers(), json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def _patch(self, path: str, data: Any) -> Dict[str, Any]:
        """
        PATCH запрос к amoCRM API.

        Args:
            path: Путь (например, /api/v4/contacts/123).
            data: Тело запроса.

        Returns:
            Ответ API.
        """
        url = f"{self.base_url}{path}"
        response = requests.patch(url, headers=self._headers(), json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    # ─────────────── Контакты ───────────────

    def _sanitize_phone(self, raw: str) -> str:
        """Очистка телефона: оставляем только цифры и '+' в начале."""
        s = raw.strip()
        if s.startswith("+"):
            return "+" + "".join(c for c in s[1:] if c.isdigit())
        return "".join(c for c in s if c.isdigit())

    def _search_contact_by_query(self, query: str) -> Optional[int]:
        """
        Поиск одного контакта по query-параметру (телефон/email/имя).
        Если найдено несколько — возвращаем первый.
        """
        if not query:
            return None
        params = {"query": query}
        result = self._get("/api/v4/contacts", params=params)
        contacts = result.get("_embedded", {}).get("contacts", [])
        if contacts:
            return contacts[0]["id"]
        return None

    def find_contact(
        self,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[int]:
        """
        Поиск контакта по телефону и/или email.

        Стратегия:
        1. Ищем по телефону (если передан).
        2. Если не нашли — ищем по email (если передан).
        3. Если не нашли ни по одному — возвращаем None.

        Args:
            phone: Номер телефона для поиска.
            email: Email для поиска.

        Returns:
            ID контакта, если найден, иначе None.
        """
        if not phone and not email:
            return None

        # Шаг 1: поиск по телефону
        if phone:
            sanitized = self._sanitize_phone(phone)
            logger.debug("Поиск контакта по телефону: оригинал=%s, очищен=%s", phone, sanitized)
            contact_id = self._search_contact_by_query(sanitized)
            if contact_id is not None:
                logger.info("Контакт найден по телефону: ID=%d", contact_id)
                return contact_id
            logger.info("Контакт по телефону %s не найден", phone)

        # Шаг 2: поиск по email (если телефон не дал результата)
        if email:
            logger.debug("Поиск контакта по email: %s", email)
            contact_id = self._search_contact_by_query(email)
            if contact_id is not None:
                logger.info("Контакт найден по email: ID=%d", contact_id)
                return contact_id
            logger.info("Контакт по email %s не найден", email)

        logger.info("Контакт не найден: phone=%s, email=%s", phone, email)
        return None

    def find_leads_by_contact(
        self,
        contact_id: int,
        pipeline_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Поиск сделок, привязанных к контакту.
        Фильтрация по статусу не передаётся в API — filter[statuses] в amoCRM API v4
        не работает корректно. При необходимости фильтр по статусу применяется в коде
        (см. has_lead_in_pipeline).

        Args:
            contact_id: ID контакта.
            pipeline_id: Опционально — ID воронки для фильтрации.
            limit: Максимум возвращаемых сделок.

        Returns:
            Список сделок (словарей).
        """
        params: Dict[str, Any] = {
            "filter[contacts][]": contact_id,
            "limit": limit,
        }
        if pipeline_id is not None:
            params["filter[pipeline_id]"] = pipeline_id

        result = self._get("/api/v4/leads", params=params)
        return result.get("_embedded", {}).get("leads", [])

    def has_lead_in_pipeline(self, contact_id: int, pipeline_id: int, status_id: Optional[int] = None) -> bool:
        """
        Проверка, есть ли у контакта сделка в указанной воронке (опционально — в указанном статусе).
        Фильтр по статусу делается в коде, т.к. filter[statuses] в amoCRM API не работает.

        Args:
            contact_id: ID контакта.
            pipeline_id: ID воронки (pipeline).
            status_id: Опционально — ID статуса для фильтрации.

        Returns:
            True если хотя бы одна сделка существует (в нужном статусе).
        """
        leads = self.find_leads_by_contact(contact_id, pipeline_id=pipeline_id, limit=250)
        if not leads:
            return False
        if status_id is not None:
            # Фильтруем в коде — проверяем что сделка в нужном статусе
            return any(lead.get("status_id") == status_id for lead in leads)
        return len(leads) > 0

    def find_lead_by_custom_field(self, field_id: int, value: Any) -> Optional[int]:
        """
        Поиск сделки по значению кастомного поля.

        Args:
            field_id: ID кастомного поля.
            value: Значение для поиска.

        Returns:
            ID сделки, если найдена, иначе None.
        """
        # Сначала пробуем фильтрацию через API (требует включения в настройках аккаунта)
        try:
            params = {
                f"filter[custom_fields_values][{field_id}][]": value,
                "limit": 1,
            }
            result = self._get("/api/v4/leads", params=params)
            leads = result.get("_embedded", {}).get("leads", [])
            if leads:
                return leads[0]["id"]
        except requests.HTTPError as exc:
            logger.warning(
                "Фильтр по кастомному полю недоступен для аккаунта (HTTP %s). "
                "Запускаю pagination fallback...",
                exc.response.status_code if exc.response is not None else "?",
            )

        # Fallback: итерация по всем сделкам с проверкой в коде.
        page = 1
        while True:
            try:
                page_params = {
                    "limit": 250,
                    "page": page,
                    "with": "custom_fields_values",
                }
                result = self._get("/api/v4/leads", params=page_params)
                leads = result.get("_embedded", {}).get("leads", [])
                if not leads:
                    break

                for lead in leads:
                    cfs = lead.get("custom_fields_values")
                    if not cfs:
                        continue
                    for cf in cfs:
                        if cf.get("field_id") == field_id:
                            for v in cf.get("values", []):
                                if v.get("value") == value:
                                    logger.info(
                                        "Сделка найдена через fallback: ID=%d, field_id=%d, value=%s",
                                        lead["id"], field_id, value,
                                    )
                                    return lead["id"]

                page += 1
            except Exception as exc:
                logger.error(
                    "Ошибка при pagination fallback (field_id=%d): %s", field_id, exc
                )
                break

        return None

    def create_contact(
        self,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        custom_fields: Optional[Dict[int, Any]] = None,
    ) -> int:
        """
        Создание нового контакта.

        Args:
            name: Имя контакта.
            phone: Номер телефона.
            email: Email.
            custom_fields: Словарь {custom_field_id: значение} для кастомных полей.

        Returns:
            ID созданного контакта.
        """
        cf_values = []

        if phone:
            cf_values.append({
                "field_code": "PHONE",
                "values": [{"value": phone}],
            })

        if email:
            cf_values.append({
                "field_code": "EMAIL",
                "values": [{"value": email}],
            })

        if custom_fields:
            for field_id, value in custom_fields.items():
                cf_values.append({
                    "field_id": field_id,
                    "values": [{"value": str(value)}],
                })

        payload = [{
            "name": name,
            "custom_fields_values": cf_values,
        }]

        result = self._post("/api/v4/contacts", payload)
        contact_id = result["_embedded"]["contacts"][0]["id"]
        logger.info("Создан контакт: ID=%d, name=%s", contact_id, name)
        return contact_id

    def update_contact(
        self,
        contact_id: int,
        custom_fields: Optional[Dict[int, Any]] = None,
    ) -> None:
        """
        Обновление кастомных полей существующего контакта.

        Args:
            contact_id: ID контакта.
            custom_fields: Словарь {field_id: значение}.
        """
        if not custom_fields:
            return

        cf_values = []
        for field_id, value in custom_fields.items():
            cf_values.append({
                "field_id": field_id,
                "values": [{"value": str(value)}],
            })

        payload = [{
            "id": contact_id,
            "custom_fields_values": cf_values,
        }]
        # Используем batch-эндпоинт /api/v4/contacts (массив), т.к. single-entity PATCH
        # ожидает объект, а не массив
        self._patch("/api/v4/contacts", payload)
        logger.info("Обновлён контакт ID=%d (добавлено %d кастомных полей)", contact_id, len(cf_values))

    # ─────────────── Сделки ───────────────

    def create_lead(
        self,
        name: str,
        contact_id: int,
        pipeline_id: int = 1,
        status_id: int = 14351486,
        responsible_user_id: Optional[int] = None,
        custom_fields: Optional[Dict[int, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """
        Создание сделки и привязка контакта.

        Args:
            name: Название сделки.
            contact_id: ID привязываемого контакта.
            pipeline_id: ID воронки.
            status_id: ID статуса.
            responsible_user_id: ID ответственного пользователя.
            custom_fields: Словарь {custom_field_id: значение}.
            tags: Список тегов для сделки (например ["VK_Lids"]).

        Returns:
            ID созданной сделки.
        """
        cf_values = []
        if custom_fields:
            for field_id, value in custom_fields.items():
                cf_values.append({
                    "field_id": field_id,
                    "values": [{"value": str(value)}],
                })

        lead_data: Dict[str, Any] = {
            "name": name,
            "pipeline_id": pipeline_id,
            "status_id": status_id,
            "_embedded": {
                "contacts": [{"id": contact_id}],
            },
        }

        if responsible_user_id:
            lead_data["responsible_user_id"] = responsible_user_id

        if cf_values:
            lead_data["custom_fields_values"] = cf_values

        if tags:
            if "_embedded" not in lead_data:
                lead_data["_embedded"] = {}
            lead_data["_embedded"]["tags"] = [{"name": t} for t in tags]

        result = self._post("/api/v4/leads", [lead_data])
        lead_id = result["_embedded"]["leads"][0]["id"]
        logger.info("Создана сделка: ID=%d, name=%s (теги: %s)", lead_id, name, tags)
        return lead_id

    # ─────────────── Утилиты ───────────────

    @staticmethod
    def auth_url(subdomain: str, client_id: str, redirect_uri: str) -> str:
        """
        Генерация URL для OAuth2 авторизации.

        Args:
            subdomain: Поддомен аккаунта.
            client_id: ID интеграции.
            redirect_uri: Redirect URI.

        Returns:
            Полный URL авторизации.
        """
        return (
            f"https://{subdomain}.amocrm.ru/oauth?client_id={client_id}"
            f"&state=leadforms&mode=post_message&redirect_uri={redirect_uri}"
        )
