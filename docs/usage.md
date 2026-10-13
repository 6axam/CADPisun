# Использование программного MVP

Интерактивный desktop workflow описан отдельно в
[`docs/gui-usage.md`](gui-usage.md). Быстрый запуск:

```sh
uv sync --python 3.12.12 --extra gui
uv run hplot-gui
```

Установка проверенной среды и тесты:

```sh
uv sync --python 3.12.12 --extra dev --extra import-svg
uv run pytest
```

Проверка покрытия без создания файлов:

```sh
uv run hplot inspect examples/first-mvp/input.txt
```

Создание атомарного bundle:

```sh
uv run hplot generate examples/first-mvp/input.txt examples/first-mvp/bundle \
  --style test-technical-v1 --style-revision 1.0.0 --seed 20261012
```

Размер страницы, единое поле, x-height, line pitch, paragraph gap и ширина пера
задаются параметрами `--page-width-mm`, `--page-height-mm`, `--margin-mm`,
`--x-height-mm`, `--line-pitch-mm`, `--paragraph-gap-mm` и `--pen-width-mm`.
Virtual profile v1 требует ширину пера 0.35 mm.

В bundle находятся исходный текст и request, pinned style manifest, PenPlan,
production/diagnostic SVG, MotionPlan, virtual G-code, отчёт и manifest с
SHA-256 каждого артефакта. `page-*.gcode` предназначен только для виртуального
профиля и не может отправляться реальному оборудованию.

`test-technical-v1` — читаемый инженерный single-line fixture для проверки
конвейера. Это малые технические прописные формы, не школьная скоропись. Он
имеет `test_only=true` и `production_eligible=false`; условия появления
настоящего `ua-school-v1` описаны в `docs/blockers.md`.

Review-only украинский пилот запускается отдельно:

```sh
uv run hplot inspect examples/ua-school-pilot/input.txt \
  --style ua-school-v1-pilot --style-revision 0.1.0 \
  --x-height-mm 4.0 --line-pitch-mm 10

uv run hplot generate examples/ua-school-pilot/input.txt /tmp/ua-school-review \
  --style ua-school-v1-pilot --style-revision 0.1.0 \
  --seed 20261013 --realism 0 --x-height-mm 4.0 --line-pitch-mm 10
```

Пилот поддерживает только символы своего word corpus и исходного малого
набора. Ошибка `MISSING_GLYPH` для остального алфавита ожидаема и не должна
обходиться fallback-символом.

