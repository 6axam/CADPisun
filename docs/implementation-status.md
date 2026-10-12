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

## I-02 — завершён 2026-10-12

- Реализована загрузка immutable StylePack v1 из каталога с безопасными путями,
  полными SHA-256, точным coverage, license record и cross-reference validation.
- Публикация новой revision проходит validation в staging и атомарно обновляет
  immutable каталог/latest; конфликт ревизий не перезаписывает данные.
- SVG authoring importer принимает только `svg/g/path`, centerline `fill=none`,
  M/L/H/V/Q/T/C/S/Z и ограниченные transforms; DTD/entities, arcs, CSS и внешние
  ссылки отвергаются.
- T-S01…T-S05 вместе с предыдущими тестами: 18/18 успешно.

## I-03 — заблокирован данными

Причина и условия снятия блокера записаны в `docs/blockers.md`. Разработка
движка продолжается на отдельном test-only стиле согласно плану.

## I-04 — завершён 2026-10-12

- Реализованы CRLF/CR→LF, extended grapheme clusters, per-cluster NFC и карта
  исходных scalar spans без замены похожих символов.
- Tailored LTR policy различает обычные/NBSP/narrow-NBSP пробелы, tab, LF и
  form-feed; запрещённые C0/bidi controls отклоняются с позицией.
- Coverage проверяет весь документ и перечисляет каждую отсутствующую графему,
  code points и исходные spans до layout/export.
- T-U01…T-U06 и весь накопленный набор: 26/26 успешно.

