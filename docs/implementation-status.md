# Состояние реализации

## I-00 — завершён 2026-10-12

- Проверенная среда: Linux 7.2.5-3-omarchy x86_64, CPython 3.12.12.
- Resolver: uv; SHA-256 `uv.lock`:
  `9df06d58d9724c3b8c12a0f4dadabd84923780e9797e9544ef48b61f802ed37d`.
- Основные pins разрешены: Pydantic 2.14.1 / pydantic-core 2.50.1,
  regex 2026.9.29.
- Dev pins разрешены: pytest 9.1.1, Hypothesis 6.169.0.
- Base install не импортирует serial, SVG importer, CV или ML.
- `hplot --help`, version и invalid-input exit code проверены автоматически.

Команда воспроизведения:

```sh
uv sync --python 3.12.12 --extra dev
uv run pytest
```

## I-01 — завершён 2026-10-12

- Добавлен immutable directed IR для Line, Quadratic, Cubic, Stroke и StrokeSet.
- Реализованы строгая canonical JSON-сериализация, запрет duplicate keys и
  нечисловых значений, именованные frames и явный Affine2.
- Bounds вычисляют внутренние экстремумы Q/C; flattening использует De Casteljau,
  предел ошибки, предел длины хорды, глубины и общего числа сегментов.
- T-G01…T-G06 и дополнительные serialization tests: 13/13 успешно.

