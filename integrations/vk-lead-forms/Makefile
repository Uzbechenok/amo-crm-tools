PYTHON ?= python3

.PHONY: install run daemon auth check clean

# Установка зависимостей
install:
	$(PYTHON) -m pip install -r requirements.txt

# Однократный прогон
run:
	$(PYTHON) main.py

# Режим демона (опрос по расписанию)
daemon:
	$(PYTHON) main.py --daemon

# Первичная OAuth2 авторизация
auth:
	@echo "Использование: make auth CODE=<код_авторизации>"
	$(PYTHON) main.py --auth-code $(CODE)

# Проверка синтаксиса Python
check:
	$(PYTHON) -m py_compile main.py
	$(PYTHON) -m py_compile vk_client.py
	$(PYTHON) -m py_compile amocrm_client.py
	@echo "✓ Синтаксис всех модулей корректен"

# Очистка мусора
clean:
	rm -rf __pycache__ *.pyc .pytest_cache
	rm -f state.json
