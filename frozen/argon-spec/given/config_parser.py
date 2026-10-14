from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    raise NotImplementedError
