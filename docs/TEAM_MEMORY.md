# TEAM_MEMORY.md — Командная база знаний

## Архитектурные решения

### 2026-05-21: Интеграция VK Lead Forms → amoCRM
- **Тип:** Интеграция
- **Язык:** Python (standalone)
- **Режим:** Polling (раз в 5 мин)
- **Репозиторий:** `amo-crm-tools/integrations/vk-lead-forms/`
- **Ветка:** `feature/vk-lead-forms-integration`
- **Статус:** Готово, ожидает данные от клиента
- **Архитектура:** Python скрипт, VK Client (leadForms.getLeads) → amoCRM API v4, state.json для last_lead_id, конфиг YAML
- **Команда:** Железяка (TL), AmoDev (разработчик), AmoTest (QA)

### 2026-05-21: Создана команда разработки
- **Тимлид:** Железяка (TG: @MyClawBasic_bot)
- **Разработчик:** AmoDev (TG: @AmoDevBot)
- **Тестировщик:** AmoTest (TG: @AmoTesstBot)
- **Правило:** ТЗ → Тимлид → Разработчик → Тестировщик → Тимлид → сдача
- **Git:** `main` (чистая) + `dev` (разработка) + `feature/*` (задачи)
