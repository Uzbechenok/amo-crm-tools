# Техническое задание: VK Lead Forms → amoCRM

**Приоритет:** Высокий
**Ветка:** `feature/vk-lead-forms-integration` (от `dev`)
**Директория:** `integrations/vk-lead-forms/`

## Цель
Создать скрипт/сервис на Python для получения лидов из VK Lead Forms и автоматического создания сделок в amoCRM через REST API v4.

## Требования

### Структура
```
integrations/vk-lead-forms/
├── config.example.yaml
├── main.py
├── vk_client.py
├── amocrm_client.py
├── requirements.txt
├── README.md
└── Makefile
```

### VK Client (vk_client.py)
- Класс VkClient(token, group_id)
- `get_lead_forms()` → получает список всех лид-форм группы
- `get_leads(form_id, limit=100)` → получает лиды конкретной формы
- Парсинг answers[] в плоскую структуру

### amoCRM Client (amocrm_client.py)
- OAuth2: получение и рефреш токена (state.json)
- `find_contact(phone, email)` → поиск контакта
- `create_contact(name, phone, email, custom_fields)` → создание
- `create_lead(name, contact_id, pipeline_id, status_id, user_id, custom_fields)` → создание сделки

### Конфиг (config.example.yaml)
```
vk.group_token, vk.group_id, vk.lead_form_id
amocrm.client_id, amocrm.client_secret, amocrm.redirect_uri, amocrm.subdomain
mapping.fields[]: vk (строка поиска) → amocrm (id стандартного поля или CF ID)
pipeline.id, pipeline.status_id, pipeline.responsible_user_id
polling.interval_minutes
```

### main.py
- Чтение конфига
- Получение лидов VK → маппинг → поиск/создание контакта → создание сделки
- State (last_processed_lead_ids, токены) в state.json
- Логирование (RotatingFileHandler)
- Обработка ошибок

### README.md
Инструкция: получение ключей, настройка OAuth, запуск.

## Критерии
- `python3 -m py_compile *.py` без ошибок
- requirements.txt
- Git: push в `feature/vk-lead-forms-integration`
