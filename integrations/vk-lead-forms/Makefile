.PHONY: install run daemon auth check clean

# Установка зависимостей
install:
	pip install -r requirements.txt

# Однократный прогон
run:
	python main.py

# Режим демона (опрос по расписанию)
daemon:
	python main.py --daemon

# Первичная OAuth2 авторизация
auth:
	@echo "Использование: make auth CODE=<код_авторизации>"
	python main.py --auth-code $(CODE)

# Проверка синтаксиса Python
check:
	python3 -m py_compile main.py
	python3 -m py_compile vk_client.py
	python3 -m py_compile amocrm_client.py
	@echo "✓ Синтаксис всех модулей корректен"

# Очистка мусора
clean:
	rm -rf __pycache__ *.pyc .pytest_cache
	rm -f state.json
