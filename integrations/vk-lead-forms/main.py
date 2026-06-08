"""
Главный модуль интеграции VK Lead Forms → amoCRM.

Запуск:
    python main.py                          # Однократный прогон
    python main.py --once                   # Однократный прогон
    python main.py --daemon                 # Постоянный режим с опросом по расписанию
    python main.py --auth-code <code>       # Первичная OAuth2 авторизация

Процесс:
1. Чтение конфига (config.yaml)
2. Получение лидов из VK (всех форм или одной)
3. Маппинг полей по конфигу
4. Поиск/создание контакта в amoCRM
5. Создание сделки в amoCRM
6. Сохранение state (ID обработанных лидов) в state.json
"""

import argparse
import json
import logging
import logging.handlers
import os
import sys
import time
from typing import Any, Dict, List, Optional

import yaml

from vk_client import VkClient
from amocrm_client import AmoCRMClient

logger = logging.getLogger("vk_lead_forms")

# Путь к файлу состояния по умолчанию
DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "config.yaml")
DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


# ─────────────────── Конфигурация ───────────────────


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Загрузка YAML конфигурации.

    Args:
        config_path: Путь к файлу конфигурации.

    Returns:
        Словарь с конфигурацией.

    Raises:
        FileNotFoundError: Если файл не найден.
        yaml.YAMLError: Если файл повреждён.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Файл конфигурации не найден: {config_path}\n"
            f"Скопируйте config.example.yaml в config.yaml и заполните данные."
        )

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    logger.info("Конфигурация загружена из %s", config_path)
    return cfg


# ─────────────────── Состояние ───────────────────


class StateManager:
    """Управление состоянием (processed lead IDs, токены)."""

    def __init__(self, state_file: str = DEFAULT_STATE_FILE) -> None:
        """
        Args:
            state_file: Путь к файлу состояния.
        """
        self.state_file = state_file
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Загрузка состояния из файла."""
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"processed_lead_ids": [], "last_run": None}

    def save(self) -> None:
        """Сохранение состояния."""
        with open(self.state_file, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def processed_lead_ids(self) -> List[int]:
        """Список ID уже обработанных лидов (с сохранением порядка)."""
        return self._data.get("processed_lead_ids", [])

    @processed_lead_ids.setter
    def processed_lead_ids(self, ids: List[int]) -> None:
        self._data["processed_lead_ids"] = ids

    def add_processed_ids(self, lead_ids: List[int]) -> None:
        """Добавление новых обработанных ID лидов."""
        current = list(self.processed_lead_ids)
        # Добавляем только новые ID, чтобы сохранить порядок
        existing = set(current)
        new_ids = [lid for lid in lead_ids if lid not in existing]
        current.extend(new_ids)
        # Не храним больше 10000 ID, чтобы файл не рос бесконечно
        if len(current) > 10000:
            current = current[-10000:]
        self.processed_lead_ids = current
        self._data["last_run"] = time.time()
        self.save()

    def update_auth_token(self, token_data: Dict[str, Any]) -> None:
        """Обновление токенов в state."""
        self._data["token"] = token_data
        self.save()


# ─────────────────── Маппинг ───────────────────


class FieldMapper:
    """Маппинг полей VK → amoCRM."""

    def __init__(self, mapping_config: Dict[str, Any]) -> None:
        """
        Args:
            mapping_config: Конфигурация маппинга из config.yaml (секция mapping).
        """
        self._fields = mapping_config.get("fields", [])

    def map_to_contact(self, answers: Dict[str, str]) -> Dict[str, Any]:
        """
        Маппинг ответов VK в структуру контакта amoCRM.
        Использует префиксы: contact_custom_XXX для полей контакта.
        Поля с lead_custom_XXX игнорируются (они для сделки).

        Returns:
            Словарь с ключами: name, phone, email, custom_fields.
            custom_fields: {field_id: value}.
        """
        name = ""
        phone = None
        email = None
        contact_custom_fields: Dict[int, Any] = {}

        for field_map in self._fields:
            vk_key = field_map.get("vk", "")
            amocrm_field = field_map.get("amocrm", "")
            value = answers.get(vk_key)

            if not value:
                continue

            if amocrm_field == "name":
                name = value
            elif amocrm_field == "phone":
                phone = value
            elif amocrm_field == "email":
                email = value
            elif amocrm_field.startswith("lead_custom_"):
                # Поле сделки — пропускаем в маппинге контакта
                continue
            elif amocrm_field.startswith("contact_custom_"):
                try:
                    custom_id = int(amocrm_field.replace("contact_custom_", ""))
                    contact_custom_fields[custom_id] = value
                except ValueError:
                    logger.warning("Некорректный custom field ID: %s", amocrm_field)
            elif amocrm_field.startswith("custom_"):
                try:
                    custom_id = int(amocrm_field.replace("custom_", ""))
                    contact_custom_fields[custom_id] = value
                except ValueError:
                    logger.warning("Некорректный custom field ID: %s", amocrm_field)
            else:
                logger.warning("Неизвестный тип поля amoCRM: %s", amocrm_field)

        return {
            "name": name,
            "phone": phone,
            "email": email,
            "custom_fields": contact_custom_fields,
        }

    def map_to_lead_custom_fields(
        self, answers: Dict[str, str]
    ) -> Dict[int, Any]:
        """
        Маппинг ответов VK в кастомные поля сделки.
        Использует префикс lead_custom_XXX для полей сделки.
        """
        lead_custom_fields: Dict[int, Any] = {}

        for field_map in self._fields:
            amocrm_field = field_map.get("amocrm", "")
            value = answers.get(field_map.get("vk", ""))

            if not value:
                continue

            if amocrm_field.startswith("lead_custom_"):
                try:
                    custom_id = int(amocrm_field.replace("lead_custom_", ""))
                    lead_custom_fields[custom_id] = value
                except ValueError:
                    logger.warning("Некорректный lead custom field ID: %s", amocrm_field)

        return lead_custom_fields


# ─────────────────── Основная логика ───────────────────


def process_lead(
    lead: Dict[str, Any],
    vk_client: VkClient,
    amocrm: AmoCRMClient,
    mapper: FieldMapper,
    pipeline_cfg: Dict[str, Any],
) -> bool:
    """
    Обработка одного лида: маппинг → поиск/создание контакта → создание сделки.

    Args:
        lead: Сырые данные лида от VK API.
        vk_client: Экземпляр VkClient.
        amocrm: Экземпляр AmoCRMClient.
        mapper: Экземпляр FieldMapper.
        pipeline_cfg: Конфигурация воронки (id, status_id, responsible_user_id).

    Returns:
        True если успешно, False если ошибка.
    """
    try:
        # Парсим ответы анкеты
        flat_lead = VkClient.flatten_lead(lead)
        # flatten_lead уже вызывает parse_answers, извлекаем поля ответов
        _vk_fields = {'lead_id', 'form_id', 'user_id', 'date', 'ad_id'}
        answers = {k: v for k, v in flat_lead.items() if k not in _vk_fields}

        logger.info("Обработка лида ID=%s", flat_lead.get("lead_id"))

        # Маппинг полей
        contact_data = mapper.map_to_contact(answers)
        lead_name = contact_data.get("name") or f"Лид VK #{flat_lead.get('lead_id')}"
        phone = contact_data.get("phone")
        email = contact_data.get("email")

        # Поиск существующего контакта
        contact_id = amocrm.find_contact(phone=phone, email=email)

        contact_custom_fields = contact_data.get("custom_fields", {})
        lead_custom_fields = mapper.map_to_lead_custom_fields(answers)

        if contact_id is None:
            # Создание нового контакта
            contact_id = amocrm.create_contact(
                name=lead_name,
                phone=phone,
                email=email,
                custom_fields=contact_custom_fields,
            )
        else:
            logger.info("Контакт ID=%d уже существует, сделка будет привязана к нему", contact_id)
            # Обновляем кастомные поля контакта (например VK_WZ)
            if contact_custom_fields:
                amocrm.update_contact(contact_id, contact_custom_fields)

        # Создание сделки
        amocrm.create_lead(
            name=lead_name,
            contact_id=contact_id,
            pipeline_id=pipeline_cfg.get("id", 1),
            status_id=pipeline_cfg.get("status_id", 14351486),
            responsible_user_id=pipeline_cfg.get("responsible_user_id"),
            custom_fields=lead_custom_fields,
        )

        return True

    except Exception as e:
        logger.error("Ошибка обработки лида %s: %s", lead.get("lead_id"), e, exc_info=True)
        return False


def run_once(config: Dict[str, Any], state: StateManager) -> None:
    """
    Однократный прогон: получить лиды VK → обработать новые.

    Args:
        config: Конфигурация приложения.
        state: Менеджер состояния.
    """
    vk_cfg = config["vk"]
    amocrm_cfg = config["amocrm"]
    mapping_cfg = config.get("mapping", {})
    pipeline_cfg = config.get("pipeline", {})

    # Инициализация клиентов
    vk = VkClient(
        client_id=vk_cfg["client_id"],
        client_secret=vk_cfg.get("client_secret", ""),
        ad_account_id=vk_cfg["ad_account_id"],
        state_file=state.state_file,
    )

    amocrm = AmoCRMClient(
        subdomain=amocrm_cfg["subdomain"],
        client_id=amocrm_cfg["client_id"],
        client_secret=amocrm_cfg["client_secret"],
        redirect_uri=amocrm_cfg["redirect_uri"],
        state_file=state.state_file,
    )

    mapper = FieldMapper(mapping_cfg)
    processed_ids = state.processed_lead_ids
    new_lead_ids: List[int] = []

    # Получение форм
    if vk_cfg.get("lead_form_id"):
        # Конкретная форма
        form_ids = [vk_cfg["lead_form_id"]]
    else:
        # Все формы группы
        forms = vk.get_lead_forms()
        form_ids = [f.get("id") for f in forms if f.get("id")]
        logger.info("Найдено форм: %d, form_ids=%s", len(form_ids), form_ids)

    # Сбор лидов по формам
    all_leads: List[Dict[str, Any]] = []
    for form_id in form_ids:
        leads = vk.get_leads(form_id)
        all_leads.extend(leads)

    logger.info("Всего получено лидов: %d", len(all_leads))

    # Фильтрация новых лидов
    new_leads = [
        lead for lead in all_leads
        if (lead.get("lead_id") or lead.get("id")) not in processed_ids
    ]
    logger.info("Новых (необработанных) лидов: %d", len(new_leads))

    # Обработка
    success_count = 0
    for lead in new_leads:
        success = process_lead(lead, vk, amocrm, mapper, pipeline_cfg)
        if success:
            lead_id = lead.get("lead_id") or lead.get("id")
            if lead_id:
                new_lead_ids.append(lead_id)
            success_count += 1

    # Сохранение состояния
    if new_lead_ids:
        state.add_processed_ids(new_lead_ids)

    logger.info(
        "Прогон завершён: всего=%d, новых=%d, успешно=%d, ошибок=%d",
        len(all_leads),
        len(new_leads),
        success_count,
        len(new_leads) - success_count,
    )


def run_daemon(config: Dict[str, Any], state: StateManager) -> None:
    """
    Запуск в режиме демона с периодическим опросом.

    Args:
        config: Конфигурация приложения.
        state: Менеджер состояния.
    """
    interval = config.get("polling", {}).get("interval_minutes", 5)
    logger.info("Запуск в режиме демона, интервал: %d мин", interval)

    while True:
        try:
            run_once(config, state)
        except Exception as e:
            logger.error("Критическая ошибка в цикле: %s", e, exc_info=True)

        logger.info("Ожидание %d мин до следующего опроса...", interval)
        time.sleep(interval * 60)


# ─────────────────── Настройка логирования ───────────────────


def setup_logging(config: Dict[str, Any]) -> None:
    """
    Настройка логирования согласно конфигу.

    Args:
        config: Конфигурация приложения.
    """
    log_cfg = config.get("logging", {})
    log_level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file")

    # Корневой логгер для модулей
    handler: logging.Handler
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_file:
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)

    root_logger = logging.getLogger("vk_lead_forms")
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    # Отключаем лишние логи библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ─────────────────── CLI ───────────────────


def main() -> None:
    """Точка входа."""
    parser = argparse.ArgumentParser(
        description="Интеграция VK Lead Forms → amoCRM"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Путь к config.yaml (по умолч: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--state",
        default=DEFAULT_STATE_FILE,
        help=f"Путь к state.json (по умолч: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Запуск в режиме демона с периодическим опросом",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Однократный прогон",
    )
    parser.add_argument(
        "--auth-code",
        metavar="CODE",
        help="Код авторизации OAuth2 для первичной аутентификации",
    )
    args = parser.parse_args()

    # Базовая настройка логирования (до загрузки конфига — в stdout)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        logger.error(e)
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error("Ошибка парсинга YAML: %s", e)
        sys.exit(1)

    # Перенастраиваем логирование после загрузки конфига
    setup_logging(config)

    state = StateManager(args.state)

    # Обработка --auth-code
    if args.auth_code:
        amocrm_cfg = config["amocrm"]
        amocrm = AmoCRMClient(
            subdomain=amocrm_cfg["subdomain"],
            client_id=amocrm_cfg["client_id"],
            client_secret=amocrm_cfg["client_secret"],
            redirect_uri=amocrm_cfg["redirect_uri"],
            state_file=state.state_file,
        )
        amocrm.authorize_from_code(args.auth_code)
        logger.info("OAuth2 авторизация завершена. Токены сохранены в %s", args.state)
        return

    # Режим демона
    if args.daemon:
        run_daemon(config, state)
        return

    # Однократный прогон (по умолчанию)
    run_once(config, state)


if __name__ == "__main__":
    main()
