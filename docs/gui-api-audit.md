# GUI-00 — аудит API для desktop application

Проверено 2026-10-13 на CPython 3.12.12, Linux x86_64, Wayland/Omarchy.

## Доступная программная вертикаль

`HandwritingPlotterService` уже выполняет полный headless pipeline без CLI и
subprocess: нормализация, coverage, StylePack loading, shaping, A4 layout,
PenPlan, production/diagnostic SVG, MotionPlan, virtual G-code и report.
`GenerationResult.files` содержит готовые bytes артефактов, поэтому GUI не
должен повторно разбирать production SVG для экспорта.

Доступные параметры ядра: A4 width/height и поля; x-height, line pitch,
paragraph gap и pen width; StylePack id/revision, seed и bounded realism;
virtual profile только для симуляции. Visibility реализуется исключением
текстового блока из generation request.

GUI не имитирует отсутствующие функции: machine send, произвольную ориентацию
страницы, редактирование Bézier nodes, OCR/capture/training, outline-font
import или физическое время неизвестного оборудования.

## Недостающая composition boundary

Обычный `build(text, request)` принимает один поток текста. Desktop document
требует несколько text objects с разными StylePack, seed, x-height и позицией.
Добавляется тонкий application-level composition API:

```text
ProjectSnapshot
  -> DesktopApplicationAdapter
  -> composed PageDocument
  -> общий PenPlan / SVG / MotionPlan / virtual G-code
```

Каждый видимый block проходит тот же `normalize → coverage → layout_document`.
Его X/Y задают левую и верхнюю координату области в PageFrame mm. Результаты
объединяются до `compile_page`; SVG и G-code сохраняют единый authority — общий
PenPlan. Первая GUI-версия явно отклоняет block, которому требуется больше
одной страницы. Модель оставляет page id/list, чтобы позже снять ограничение
без замены формата проекта.

## Canvas

Canvas использует `QGraphicsScene` в миллиметрах и отображает backend bytes:
production SVG, diagnostic SVG и PenPlan JSON для start/end markers и
toolpath statistics. Диагностические items существуют только в scene и не
добавляются в production SVG или G-code.

## Асинхронная модель

Синхронный deterministic backend запускается через `QThreadPool/QRunnable`.
Snapshot получает monotonically increasing document revision. Одновременно
разрешена одна job; результат применяется только при совпадении revision.
Существующий `CancellationToken` ещё не подключён ко всем длительным этапам,
поэтому GUI не показывает фиктивную кнопку отмены.

## Project format

`hp-desktop-project/1.0` — canonical UTF-8 JSON. Источник истины — page
settings, text objects, style references, positions и generation/display
settings. Generated artifacts не обязательны. Save выполняется через temporary
file, fsync и `os.replace`; абсолютные пути не записываются. Неизвестная schema
version отклоняется.

## Qt и лицензирование

Выбран PySide6 6.12.0 как optional extra `gui`; wheel заявляет Python
3.10–3.15, включая 3.12. Community distribution доступна под LGPLv3/GPL,
также существует commercial distribution. CLI и core не импортируют PySide6.

Wayland используется через Qt platform plugin. Код не обращается к X11 API и
не задаёт `QT_QPA_PLATFORM`; `offscreen` применяется только в UI tests и
screenshot QA.
