"""
Утилиты для атомарной работы с state.json с файловой блокировкой.

Все три компонента (StateManager, AmoCRMClient, VkClient) пишут в один state.json.
Без блокировки параллельные процессы перезаписывают изменения друг друга.
"""

import fcntl
import json
import logging
import os
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def locked_update_state(
    state_file: str,
    update_func: Callable[[Dict[str, Any]], None],
) -> None:
    """
    Атомарное чтение-модификация-запись state.json с эксклюзивной блокировкой.

    Использует fcntl.flock с LOCK_EX для предотвращения race condition
    между параллельными процессами.

    Args:
        state_file: Путь к файлу состояния.
        update_func: Функция, которая получает текущие данные (dict)
                     и модифицирует их. Данные будут записаны обратно.
    """
    # 'a+' создаёт файл если его нет, не усекает
    with open(state_file, "a+") as f:
        # Эксклюзивная блокировка — ждём, пока другой процесс не отпустит
        fcntl.flock(f, fcntl.LOCK_EX)

        try:
            # Читаем текущие данные
            f.seek(0)
            raw = f.read()
            if raw.strip():
                data = json.loads(raw)
            else:
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Ошибка чтения state.json, начинаем с пустого: %s", e)
            data = {}

        # Модифицируем
        update_func(data)

        # Пишем обратно
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

        # Блокировка снимается при закрытии файла,
        # но снимаем явно чтобы освободить раньше
        fcntl.flock(f, fcntl.LOCK_UN)
