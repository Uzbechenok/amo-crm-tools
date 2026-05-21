# Интеграция VK Lead Forms → amoCRM

Скрипт для автоматической передачи лидов из VK Lead Forms в amoCRM (REST API v4).

## Архитектура

```
VK API ──→ vk_client.py ──→ main.py ──→ amocrm_client.py ──→ amoCRM API v4
                                │
                          config.yaml
                          state.json
```

## Быстрый старт

### 1. Получение ключей VK

1. Перейдите в **Управление сообществом** → **Работа с API** → **Создать ключ доступа**
2. Выберите права: `leads`, `groups`, `wall`, `stats`
3. Скопируйте полученный токен — это `vk.group_token`

### 2. OAuth2 авторизация amoCRM

1. Создайте интеграцию в amoCRM: **Настройки** → **API** → **Создать интеграцию**
2. Укажите Redirect URI (например, `https://your-domain.com/oauth/callback`)
3. Скопируйте `client_id` и `client_secret`
4. Откройте в браузере ссылку для авторизации:
   ```
   https://{subdomain}.amocrm.ru/oauth?client_id={client_id}&state=leadforms&mode=post_message&redirect_uri={redirect_uri}
   ```
5. После подтверждения — скопируйте код авторизации из URL (параметр `code`)
6. Выполните:
   ```bash
   python main.py --auth-code <КОД>
   ```

### 3. Настройка конфига

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml, заполнив все поля
```

### 4. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 5. Запуск

```bash
# Однократный прогон
python main.py

# Режим демона (опрос по расписанию)
python main.py --daemon
```

## Структура проекта

```
integrations/vk-lead-forms/
├── amocrm_client.py       # Клиент amoCRM REST API v4
├── vk_client.py           # Клиент VK Lead Forms API
├── main.py                # Оркестрация (точка входа)
├── config.example.yaml    # Пример конфигурации
├── config.yaml            # Рабочий конфиг (создаётся пользователем)
├── state.json             # Состояние (токены, обработанные лиды)
├── requirements.txt       # Зависимости Python
├── README.md              # Документация
└── Makefile               # Команды для сборки/запуска
```

## Формат state.json

```json
{
  "processed_lead_ids": [1, 2, 3],
  "last_run": 1712345678.123,
  "token": {
    "access_token": "...",
    "refresh_token": "...",
    "expires_at": 1712345678
  }
}
```

## Режимы работы

| Аргумент | Описание |
|----------|----------|
| _(без аргументов)_ | Однократный прогон |
| `--once` | Однократный прогон (явно) |
| `--daemon` | Бесконечный цикл с опросом по расписанию |
| `--auth-code CODE` | Первичная OAuth2 авторизация по коду |
| `--config PATH` | Указать путь к конфигу |
| `--state PATH` | Указать путь к state.json |

## Логирование

- По умолчанию: stdout
- В config.yaml можно указать `logging.file` — файл с ротацией (10 MB × 5 файлов)
- Уровень: `logging.level` (DEBUG, INFO, WARNING, ERROR)

## Обработка ошибок

- **VK API ошибки:** логируются, лид пропускается
- **Сетевые ошибки:** retry через requests (timeout 30s)
- **Проблемы с токенами:** автоматический refresh OAuth2
- **Дубликаты:** контакты ищутся по телефону/email перед созданием

## Лицензия

MIT
