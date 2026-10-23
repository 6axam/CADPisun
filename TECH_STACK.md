# Технологический стек и политика зависимостей

Срез 2026-10-12. Pins ниже разрешены и проверены в I-00 на CPython 3.12.12/Linux x86_64; точные transitive версии и hashes находятся в `uv.lock`, отчёт — в `docs/implementation-status.md`. Не заменять эти версии свежими автоматически.

## 1. Основное окружение

CPython **3.12.x**, первоначально поддерживается только эта minor-ветка. Конкретный поддерживаемый patch фиксируется при I-00 вместе с platform и wheel hashes. Причина: достаточно современный язык, совместимость с проверенными пакетами и будущими ML окружениями; системный Python rolling-release Arch не является reproducibility boundary. Виртуальное окружение проекта отдельно, системные packages не менять.

| Инструмент / стартовый pin | Назначение и причина | Лицензия / ограничения | Альтернатива и замена |
|---|---|---|---|
| stdlib: dataclasses, math, hashlib, json, pathlib, argparse, unicodedata, XML writer | Математика ограниченных кривых, DTO внутри ядра, hashes, CLI и files без framework | Python license; Unicode normalization version фиксируется runtime | При performance bottleneck заменить лишь geometry internals, сохранив IR |
| [Pydantic 2.14.1](https://pypi.org/project/pydantic/2.14.1/) | Валидация внешних models, JSON Schema, strict mode | MIT; Python ≥3.10; pydantic-core 2.50.1 содержит native wheel | dataclasses + jsonschema behind serializers; бизнес-инварианты в собственном модуле |
| [regex 2026.9.29](https://pypi.org/project/regex/2026.9.29/) | Extended grapheme clusters `\X`, свойства Unicode | Metadata: Apache-2.0 AND CNRI-Python; Python ≥3.10, ориентирован на CPython | ICU/uniseg при новых scripts; сохранить графемные/source-map fixtures |
| [svg.path 7.1](https://pypi.org/project/svg.path/7.1/) — extra import-svg | Парсер команд path без numpy/scipy | MIT; Python ≥3.8, обязательных runtime deps нет | svgpathtools 1.8.0 либо svgelements; переводить в собственные primitives |
| [defusedxml 0.7.1](https://pypi.org/project/defusedxml/0.7.1/) — extra import-svg | Безопасный XML reader для imports | PSFL; дополнительно собственные limits/allowlist | lxml с выключенными entities/network через тот же importer port |
| sqlite3 stdlib — только II | Catalog транскрипций, revision и correction events | SQLite public domain; реальные версии runtime записывать | Другой local store через Repository ports; не менять StylePack |

Pydantic используется только для validation, без облачных сервисов/Logfire. [Strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) не освобождает от finite-number, duplicate-key и cross-reference проверок. Конвертация JSON numbers в float разрешена явно; coercion строк «10mm» в число не разрешена.

Размер base dependency graph невелик, но это не «полностью pure Python»: regex и pydantic-core имеют native части. Если нет wheel для выбранной платформы, I-00 фиксирует проблему и выбирает доступную совместимую версию, а не молча ставит toolchain в систему.

### Desktop GUI extra

| Pin | Назначение | Лицензия / границы |
|---|---|---|
| PySide6 6.12.0 — extra `gui` | Официальные Qt 6 bindings; Qt Widgets, QMainWindow/QDockWidget, QGraphicsView, QtSvg; wheel поддерживает Python 3.12 | Community LGPLv3/GPL или commercial; не импортируется core/CLI |
| pytest-qt 4.5.0 — extra `gui-dev` | Event-loop aware widget tests | MIT; только development/test environment |

Первичная платформа — Linux Wayland. Qt сам выбирает platform plugin; код GUI
не вызывает Xlib и не принуждает XWayland. `QT_QPA_PLATFORM=offscreen`
разрешён только для CI/визуального render smoke test.

Photo ingest v1 использует `QImageReader` из того же PySide6 extra как narrow
decoder adapter для PNG/JPEG/WebP и дополнительных явно разрешённых raster
formats. Core photo models/repository не импортируют Qt; base dependency graph и
CLI остаются прежними. OpenCV не добавляется ради TASK 01 и впервые понадобится
только для preprocessing после отдельного vision lock.

## 2. Тестовые зависимости

| Pin | Роль | Лицензия / граница |
|---|---|---|
| [pytest 9.1.1](https://pypi.org/project/pytest/9.1.1/) | Модульные и end-to-end проверки | MIT, Python ≥3.10, только dev |
| [Hypothesis 6.169.0](https://pypi.org/project/hypothesis/6.169.0/) | Инварианты геометрии, Unicode, state machines | MPL-2.0 в текущей metadata, Python ≥3.11; dev, не runtime |
| svgpathtools 1.8.0 — optional verification | Независимая оценка bounds/curves в избранных tests | MIT, numpy/scipy/svgwrite transitive; не нужен пользователю |

Не требовать Qt/OpenGL/browser automation для базового CI. SVG validity проверяется XML и нашим subset validator; визуальная приёмка дополнительно проводится существующим viewer. Если в дальнейшем нужен растровый snapshot renderer, выбрать и зафиксировать отдельный dev extra после проверки его Linux system dependencies. Сам факт корректного XML не доказывает правильное письмо.

## 3. Аппаратное окружение I-H

[pySerial 3.5](https://pypi.org/project/pyserial/3.5/) — единственный обязательный кандидат serial extra; [BSD-3-Clause](https://github.com/pyserial/pyserial/blob/a5c48d445fbc1943d4fabf8d9090a50fda3172fd/LICENSE.txt). Нет протокола CNC, ретраев движения или буферного planner внутри serial library. Последний просмотренный default-branch commit — 2026-02-27; отсутствие нового release само по себе не доказывает ни заброшенность, ни совместимость с любым Python.

Альтернатива: существующий Universal Gcode Sender для первого стенда; наш direct sender не обязателен для первого физического теста экспорта. Ethernet/USB vendor SDK — только отдельный Transport/Backend. Прошивка выбирается механической командой и не входит в dependency lock Python. Не предполагается Arduino, GRBL или FluidNC по умолчанию.

## 4. Vision окружение II-B

Отдельный локальный venv `vision`, Python 3.12. Обмен через DTO/job files. Стартовые кандидаты:

| Компонент | Роль | Ограничения и замена |
|---|---|---|
| [opencv-python-headless 4.13.0.92](https://pypi.org/project/opencv-python-headless/4.13.0.92/) | Decode, homography, deskew, masks, morphology | Apache-2.0 metadata плюс third-party notices wheels; numpy≥2 на Python3.12. Не ставить одновременно opencv-python и headless. 5.0.0.93 обнаружен, но major upgrade отложен |
| [scikit-image 0.26.0](https://pypi.org/project/scikit-image/0.26.0/) | skeletonize, threshold tools | Python≥3.11, BSD-family/MIT per-file notices; numpy/scipy/networkx/Pillow и др. Следовать polylines/graph output contract, не считать skeleton trajectory |
| numpy 2.x / scipy / Pillow | Transitive массивы/фильтры/изображения | Точный совместимый lock решается при II-B; лицензии wheels/BLAS также записываются |

Если OpenCV тяжёл/недоступен, preprocessing может быть перенесён на skimage через ImagePreprocessor port; это не меняет source assets или correction model. Не устанавливать второй numerical stack в base venv «на будущее».

## 5. HTR окружение II-B/II-C

Основной backend **Kraken stable 7.1.1**, отдельный `htr-kraken` venv, Python3.12. [Опубликованные требования](https://pypi.org/project/kraken/7.1.1/): Python≥3.10,<3.14; scikit-image ~0.25.2, scipy ~1.15.3, Lightning 2.6.1, torch≥2.9,≤2.14, coremltools ~9, torchvision и другие пакеты. Code Apache-2.0; каждая segmentation/recognition model имеет собственную license/codec/training provenance.

**Установленное по metadata противоречие:** vision skimage0.26.0 не удовлетворяет требованию Kraken7.1.1 `~0.25.2`. Поэтому выбран отдельный process/env, а не общий extras resolver. Main ветка Kraken имеет иные диапазоны и API; не проектировать stable adapter по одному исходнику main. При II-B зафиксировать source tag/commit, соответствующий wheel7.1.1, и его API. До этого конкретное имя task class внутри адаптера не является межмодульным контрактом.

Для ThinkPad CPU — обязательный fallback inference. AMD CPU не означает доступный CUDA GPU. ROCm, дискретная GPU и объём RAM неизвестны. Для обучения допускается позднее отдельно согласованный compute, но продукт не требует платных API. До benchmark не обещать минутное обучение на ноутбуке.

Альтернативы: TrOCR через отдельный recognizer adapter; CRNN-CTC украинской модели — сравнительный кандидат с отдельным loader. Выбор готовых весов **не зафиксирован**: он зависит от собственного corpus benchmark и подтверждённых прав. Фиксированы backend interface, baseline engine, split/metrics и gate выбора; это экспериментально зависимое решение, а не произвольный выбор будущего разработчика.

## 6. Исследовательское окружение реконструкции

InkSight Small-p допускается только после E-07 из RISKS. [Текущий code environment](https://github.com/google-research/inksight/blob/486d4772e2fdd187f0c3416a41479b1ffc080c66/pyproject.toml) использует TF2.20.0/text2.20.1, а [card](https://huggingface.co/Derendering/InkSight-Small-p) рекомендует2.15–2.17. Это открытая compatibility gate. Нельзя одновременно назвать обе конфигурации проверенными.

План: отдельный pinned CPU-compatible env; выбрать конфигурацию после воспроизведения официального fixture, записать source SHA/weight SHA/env lock; только затем сравнивать UA samples. Не включать CUDA packages с незнакомыми GPU предпосылками. Если gate не пройден — manual reconstruction остаётся основным, нейромодель не блокирует продукт.

## 7. Лицензионная политика и provenance

1. Собственный код планируется MIT. Это рекомендация, не выдача прав от имени автора ещё не созданного ПО.
2. Для каждого vendored/imported asset сохранять источник, конкретную ревизию, copyright/license text, attribution и допустимость перераспространения. Код, шрифт, dataset, trained weights — четыре отдельные записи.
3. VHS/Tracer AGPL не копируются в core. Tracer может применяться отдельно автором для записи собственных штрихов; импорт данных не равен включению его UI/исходников. Лицензию самих образцов задаёт их правообладатель.
4. Для файлов с OFL сохранять OFL и reserved font name условия; не объявлять их MIT из-за лицензии wrapper. Default style авторский, чтобы не зависеть от сомнительной смеси font files.
5. У двух исходных кандидатов явная license не обнаружена. Не считать это разрешением на включение. [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) объясняет, почему public repository и licensed open source — разные условия.
6. IAM и HKR с non-commercial ограничениями не становятся bundled production training corpus автоматически. Собственный corpus имеет consent/rights manifest; privacy по умолчанию local.
7. Удаление/отзыв исходного sample из будущего обучения выполняется через новую snapshot/revision; существующие модели нельзя объявить «забывшими» пример без переобучения/проверки.

Это практическая политика выбора компонентов; перед внешним распространением конкретного набора — проверка его фактических лицензий, а не обещание юридической совместимости ещё не собранного дистрибутива.

## 8. Установка, фиксация и ремонтопригодность

Будущий проект использует стандартный pyproject и venv/pip; optional extras `import-svg`, `serial`, `dev`. Vision/HTR — отдельные locks и не импортируются из `__init__`. Нет обязательных Docker, Node, Electron, FastAPI, Redis, Postgres, PyTorch/TF в MVP.

I-00 создаёт base lock с exact transitive versions и hashes из выбранных distributions, фиксирует Python patch и architecture. Каждый adapter тестируется на golden fixtures upstream и наших контрактов. Обновление dependency — отдельное изменение lock + relevant contract tests. Если upstream прекращает сопровождение, immutable data schema и port позволяют заменить один adapter; собственный Stroke IR остаётся рабочим.

Network нужен при первоначальной установке зависимостей или явной загрузке будущих проверенных весов; generated pages и styles не отправляются наружу. Base/dev/import-svg зависимости установлены в отдельное `.venv`; vision/HTR/serial не устанавливались.
