# Последовательность будущей реализации

Это план для отдельной команды/последующего запуска Codex. **Ни один пакет здесь сейчас не выполняется.** Созданы только Markdown-документы. Перед реализацией нужна отдельная прямая команда пользователя.

Порядок чтения: README → DECISIONS → DATA_MODELS → MODULE_CONTRACTS → ARCHITECTURE → этот план → TEST_STRATEGY. Имена файлов далее — будущие deliverables; их наличие не предполагается. До завершения ворот этапа следующий зависимый пакет не объявлять готовым.

## 1. Общий Definition of Done

У каждого пакета есть контракты, positive/negative tests и артефакт приёмки. Нет TODO в обязательном data path, неявных default hardware values, молчаливого пропуска символов и импорта optional dependencies в core. Выполненные изменения документируются вместе с проверенной версией зависимостей. Тесты подтверждают поведение/инвариант, не копируют алгоритм реализации.

В production package нельзя временно оставить fake style под видом готового почерка. Синтетические простые glyph fixtures допустимы для тестов с явной маркировкой `test-only`. Для появления реального шрифта требуется работа автора и review; Codex не должен объявлять эту ручную работу выполненной без данных.

## 2. Этап I — законченный программный MVP

### I-00. Каркас и воспроизводимое окружение

**Зависимости:** только архитектурное разрешение на начало. **Цель:** проверить, что выбранный минимальный стек устанавливается на Linux без ML и устройства.

Создать pyproject.toml, package `src/handwriting_plotter`, `tests`, `docs`, package metadata и стандартный CLI entrypoint; перенести/сослаться на эту спецификацию без изменения `sources/`. Зафиксировать Python3.12 patch, Pydantic2.14.1, regex2026.9.29, dev pins и hash lock после реального resolver check. Import-svg и serial отдельны; никакой установки vision.

Данные/контракты: пока только версии приложения, diagnostic model, exit-code policy. Файлы: `domain/errors.py`, `application/jobs.py`, `cli.py`, environment lock, `tests/test_installation.py`.

Проверка T-A01: установка из чистого venv, импорт без serial/CV/torch, CLI help/invalid input exit codes, offline no-download behaviour. Сложность: доступность wheels и несовпадение Arch system Python. Готово: есть reproducible base install report, а не только предположение по metadata. Если pins не разрешаются, изменить TECH_STACK/ADR и зафиксировать новый реальный lock.

### I-01. Canonical models, serialization и геометрия

**Зависит:** I-00. Создать `domain/{models,ports}.py`, `geometry/{curves,transforms,bounds,flatten,collision}.py`, JSON schema exports и `tests/geometry`.

Спецификация: DATA_MODELS §§1–3,7; MODULE_CONTRACTS §2. Реализовать только Line/Q/C, directed Stroke, frames, validation, affine transforms, curve bounds и conservative subdivision. Сохранить общие endpoints. Не писать свой универсальный SVG parser и не добавлять arcs.

Вход: valid/invalid declarative fixtures. Выход: validated IR + reports. Tests T-G01…T-G06: degenerate curves, loop с совпадающими endpoints, inf/NaN, transform inverse, extremum вне endpoints, bounded flatten и resource cap. При необходимости независимый svgpathtools oracle — только dev.

Ожидается: маленькое библиотечное ядро без внешних effect. Сложность: численная вырожденность и ошибочное превращение loops в нулевой сегмент. Готово: при invalid data строгий отказ; валидные кривые сохраняют bounds и направление в заявленном tolerance.

### I-02. StylePack и контролируемый импорт

**Зависит:** I-01. Создать `styles/{repository,validation,coverage,revision}.py`, `adapters/importers/svg_paths.py`, fixtures собственных SVG, draft schema и reports.

Реализовать load/validate/publish immutable revision, проверку file hashes/provenance/coverage, implicit immutable snapshot. Import SVG пути через defusedxml+svg.path по ограниченному subset. Поддержку SVG font оформить отдельным адаптером только если нужен выбранный источник; не задерживать авторские paths ради полного стандарта SVG.

Вход: каталог authoring files + metadata; выход: StyleDraft/StyleSnapshot. Соединения без anchors запрещены. Version migration v1 loader отвергает будущие major. T-S01…T-S05: malformed XML, external entities, missing key, hash mismatch, discontinuous paths, duplicate variant ID, license missing, rollback publish.

Готово: тестовый стиль полностью проходит validator и импорт сохраняет stroke order; нет заявления, что это готовый UA стиль. Риск: графически правильный SVG может быть outline — manual centerline review обязателен.

### I-03. Подготовка и приёмка `ua-school-v1`

**Зависит:** I-02; первичный сбор образцов может идти раньше I-02, но publication — только после него. **Это критический путь качества, отдельный от кода.**

Создать `assets/styles/ua-school-v1/<revision>/` с manifest/glyphs/provenance/licenses/review, исходные авторские векторы, coverage table и листы пар. Основной способ — существующий SVG editor + directed centerlines/sidecars; optional external Tracer raw capture после готовности соответствующего importer. Не создавать UI сборщика.

Сначала E-01 пилот 20 трудных символов; если качество плохое — переработать формы/anchors до полного набора. Затем весь точный coverage из DATA_MODELS §3.3. Для каждой уникальной строчной графемы минимум3 принятых варианта; для прописных/цифр/пунктуации минимум1. Буквы UA/RU с общим code point имеют один набор; Latin/Cyrillic keys раздельны.

Подготовить typed metadata entry/exit, tangent classes, body/marks, safe ranges; минимум по5 проверенных пар на каждый используемый anchor class pair и все pair exceptions. Слова `ґрунт`, `Європа`, `Україна`, `її`, `під’їзд`, `об'єкт`, `ймовірність`, `ёж`, `съезд`, `QX`, `minimum`, `шишки` обязательны для визуального review.

Приёмка T-S02/T-J07/V-01/V-02: полное покрытие, нет outline tracing, нужные marks сохранены, связность и читаемость по frozen corpus. **Не завершать пакет одним автоматически нарисованным алфавитом.** Выход: approved revision и кто/что проверил. Если качественного автора/набора пока нет — engine может разрабатываться дальше на test fixtures, выпуск MVP остаётся заблокирован данными.

### I-04. Unicode pipeline

**Зависит:** I-01/I-02; использует test style до I-03. Файлы `text/{normalize,segment,breaks,coverage}.py`, `tests/text`.

Реализовать NFC с source map, extended graphemes, literal Unicode coverage, whitespace/control/break policy. Coverage делается для всего job до page/export. Никаких model sanitizers. Tests T-U01…T-U06; exhaustive обязательный набор, decomposed marks, lookalikes, apostrophes, controls, unknown emoji и duplicate source accounting.

Готово: каждый исходный символ либо представлен графемой/контролом, либо указан в ошибке, никаких молчаливых потерь. Полезный результат: команда inspect сообщает все недостающие glyphs и позиции.

### I-05. Shaping, variants и joins

**Зависит:** I-01/I-02/I-04; качество подтверждается с I-03. Файлы `shaping/{resolve,variants,placement,joins,schedule}.py`, `tests/shaping`, corpus pair fixtures.

Точный алгоритм ARCHITECTURE §§5–6: longest-match trie, stable occurrence IDs, hash-derived choices, bounded transforms, direct cubic connector, clearance veto, deterministic fallback и scheduling body/marks. Не начинать с generic noise или nearest-neighbour sort. Imported style без join metadata работает несоединённым.

Вход: normalized fragment + pinned style/seed, выход ShapedWord. Tests T-J01…T-J07/T-R01…T-R03: все pair classes, forbidden boundaries, перенос ligature на позднем этапе, і/ї/й delayed marks, repeats, pathological overlaps.

Готово: повторяемые words, source coverage, проверенные connectors, ни одной случайной связи между словами. Сложность: data-dependent качество не измеряется только unit tests; E-02 pair corpus review обязателен перед release.

### I-06. Вёрстка страниц

**Зависит:** I-05. Файлы `layout/{lines,pages}.py`, `tests/layout`.

Реализовать layout с WordShaper port, greedy по occupied envelopes, no-break groups, hard/page breaks, emergency grapheme splitting с reshaping, effective line pitch и pagination. Размер mm из DATA_MODELS, variation заморожена до измерения. Фактический printable envelope учитывает pen width.

Tests T-L01…T-L07: короткая строка; multiline paragraph; ≤/≥ edge bounds; 10 страниц; oversized glyph; NBSP overflow; длинный URL/слово; лигатура на разрыве; negative bearings; marks/descenders соседних строк. Не использовать char-count wrapping.

Готово: source coverage100%, ноль выхода чернил за printable region и детерминированные page breaks. Ошибка не порождает обрезанную production страницу. После этого уже можно видеть цельный текст через будущий SVG writer.

### I-07. PenPlan, SVG и логическая симуляция

**Зависит:** I-06. Файлы `strokes/{compile,validate,simulate}.py`, `adapters/svg/{writer,preview}.py`, `tests/pen_plan`, `tests/svg`.

Вход PageDocument, выход PenPlans, чистые/diagnostic SVG и reports. Реализовать finite-state checks, lengths/lifts, numbered preview/travel segments. Производственный SVG без `<text>` и glyph outlines; тот же порядок/геометрия, что у PenPlan. Не запускать sender.

Tests T-P01…T-P04/T-E01…T-E03: pen-up перед travel, ordered marks, финальный UP, валидный XML, физические размеры, comparison SVG geometry vs plan. Manual preview V-01/V-02 в существующем viewer.

Готово: полностью локальный preview для нескольких страниц и deterministic diagnostic outputs; diagnostic artifact отвергается motion API. Это законченная промежуточная вертикаль text→page, но ещё не финальный MVP.

### I-08. Виртуальный MotionPlan и G-code

**Зависит:** I-07. Файлы `motion/{profiles,registration,preflight,planning,limits,timing}.py`, `adapters/gcode/{base,virtual_xyz,parser}.py`, `profiles/virtual-cartesian-z-v1.json`, `tests/motion`.

Реализовать synthetic profile строго DATA_MODELS §6, transforms, mm/s→F, flatten/quantize/revalidate, synchronized Z/settle transitions, separate page artifacts. Independent restricted decoder, modal simulation и round-trip comparisons. Реальный GRBL profile не создаётся по аналогии.

Tests T-M01…T-M07/T-E04…T-E07: mirror/rotation, pen actuation, all-move bounds, rounding у лимита, control injection, profile hash mismatch, zero-length critical mark, unknown axes. Никакого default G0 или M3.

Готово: экспорт valid **virtual dialect** и проверка complete script без порта. В manifest явно simulation_only=true. Physical assertions не допускаются. E-03/E-04 — численные/сквозные эксперименты будущей реализации.

### I-09. CLI, bundle и выпуск программного MVP

**Зависит:** I-00…I-08, включая принятый реальный StylePack I-03. Файлы `application/service.py`, `storage/files.py`, CLI commands, packaged assets, usage docs, `tests/e2e`.

Собрать inspect/generate/export/simulate/styles validate. CLI принимает UTF-8 file, style revision, seed, page settings; сохраняет bundle атомарно. Profiles и formats явны. Код библиотеки и CLI используют одни services, но CLI error handling не течёт в models. Отмена между words/pages не публикует completed manifest.

Run all core tests + acceptance corpus. T-A02…T-A04: неизвестная буква на последней странице блокирует job, disk-full сохраняет существующие данные, одинаковые inputs byte-identical при pinned env, offline test, no optional import. Начальный performance target:10 страниц около20 000 графем за≤30s и≤512MiB resident memory на записанной CPU конфигурации; это проверяемая цель, не обещание для любого AMD ThinkPad.

Готово: из arbitrary supported UA text получается проверенный многостраничный SVG/PenPlan/virtual G-code bundle, reports и воспроизводимый manifest. Выпуск маркируется «software validated, hardware unverified». Если quality gate почерка не пройден, не менять название критерия на «технически работает».

## 3. I-H — реальное устройство, отдельный gate

### H-00. Паспорт оборудования и калибровка

Начинается после выбора механики. Получить ответы Q-H из RISKS: размеры/кинематика/firmware/pen/axes/origin/limits/transport/fail-safe. Создать documentary profile, calibration record и evidence для capabilities. До физического шага профиль simulation-only. Нельзя угадать M3/M5/servo polarity.

Калибровочные задания будущих испытаний: рамка, диагонали, известные отрезки, повторные подъёмы, точки и перо на чистом листе; сначала pen-up dry run. Измерить scale/skew, backlash, settling, допустимые feeds/acceleration, реальную width и reproducibility. Данные применяются только через новый profile revision.

Приёмка H-A/H-B: согласованная registration и error budget, все travel допустимы, pen действительно поднимается. Если рабочего поля не хватает для A4 printable region, экспорт отклоняется; tiled writing не добавлять неявно.

### H-01. Конкретный dialect и транспорт

Файлы выбранного backend, `adapters/transport/{serial,fake}.py`, `machine/{session,protocol,journal}.py`, contract tests. pySerial3.5 только при serial устройстве. Если firmware не имеет planner, сначала отдельный backend design gate; Python не должен сам выдавать step timing.

Реализовать identification/readback/capability checks, start/hold/abort/drain, incremental parser, timeout handling, no automatic movement retry. До станка fake protocol tests T-H01…T-H06. Затем совместимость реальных emitted commands H-C на коротком задании. Существующий sender допустим как независимая проверка; direct send не внедрять прежде экспортера.

### H-02. Physical release

Сравнить скан/измерение результата с планом, проверить отсутствие лишних линий, работу dots/joins, отсутствие пропуска шагов, продолжительный многостраничный workflow с ручной сменой листа. E-05 и H-D. Physical repeatability target предварительно ≤0.2mm при принятом размере букв; окончательный предел зависит от механики/ручки и фиксируется до прогона.

Выпуск завершён только с named firmware/version/profile/calibration, протоколом проверки и ограничениями. Нельзя распространить его заключение на другие контроллеры автоматически.

## 4. Этап II — персональный профиль

### II-00. Каталог, correction journal и импорт online

**Зависит:** I-09; реальный станок не нужен. Файлы `storage/catalog.py`, migrations, `learning/{ingest,corrections}.py`, `adapters/importers/tracer_json.py`, online schema.

Implement SourceAsset/OnlineCapture/CorrectionEvent/StyleRevision. Первым поддержать `tracer-capture/1` JSON; InkML добавить вторым отдельным importer с явными channel units. Старые VHS/Tracer версии либо explicit migration, либо error, не эвристика по имени файла. Образцы x/y/t/pressure не подменяются SVG pressure outlines.

Tests T-D01…T-D05: timestamps, неизвестная pressure, source rights, stale revision conflict, transactional rollback, повторяемая нормализация. Выход — персональные approved variants, импортируемые общим I generator. Дополнительный ML не нужен. После этого уже доступна честная персонализация по записанным движениям.

### II-01. Корпус и ground truth

До выбора pretrained model сформировать pilot dataset со своим автором и разрешёнными источниками. Начальный бюджет сбора, не обещание достаточности:

- 300 размеченных строк UA/RU/EN не менее чем из10 страниц и3 отдельных сессий; 200 train,50 validation,50 test, **разделять целыми сессиями/страницами**, при невозможности точных чисел округлять и документировать.
- Для всех обязательных букв ≥3 online samples, для проблемных форм/anchors ≥5; 200 пар и100 новых слов, не копий шаблона, с настоящим порядком пера.
- Для reconstruction paired subset ≥100 слов: online recording + его raster render и отдельная фотография реально написанного образца, когда такая связь достоверна. Rendered image и photo не объявляются одним распределением.
- Разметить transcriptions, line polygons/baselines, ink masks для оценочного subset, критические marks, известные glyph boundaries/ligatures и uncertainty. Не заставлять annotator выдумывать однозначную границу.

Файлы будущего dataset manifest/split/review protocols; данные private по умолчанию. Расширять обучение до нескольких тысяч строк по learning curves, а не заявлять, что 300 строк решают HTR. External IAM/HKR только для разрешённого comparison без leakage в production datasets.

Готово: immutable snapshot, тестовая часть закрыта для подбора параметров, train/test нет одного writer при оценке cross-writer generalization. Для персонального same-writer режима разделение по сессиям, не требование разных людей.

### II-02. Vision и line segmentation

**Зависит:** II-00/II-01. Env vision из TECH_STACK. Файлы `learning/{preprocess,regions}.py`, ImagePreprocessor/Segmenter adapters, job protocol, overlays.

Реализовать orientation/corners/homography/deskew/background, сохранить transforms, отдельно binary/HTR изображения. Сначала ручные corners/polygons как надёжный baseline; затем автоматические proposals. Lines через выбранный Kraken segmentation checkpoint после license/codec checks; отсутствие подходящей модели не блокирует ручную разметку.

Tests T-C01/T-C02/E-06: flat page registration error, линованная бумага, тени, page not found, не удалять точки. Ожидается proposal quality report и обратное отображение crop→source. Curved pages дают DEWARP_REQUIRED/ручной crop, не неверную физическую шкалу.

### II-03. HTR baseline и выбор weights

**Зависит:** II-02. Env htr-kraken отдельно, actual stable API pinned. Files `adapters/htr/kraken.py`, `learning/recognition.py`, ModelRegistry, EvaluationReport.

Сравнить (1) подходящую Kraken Cyrillic модель, если её rights/codec прошли; (2) training/fine-tuning Kraken на собственном corpus; (3) украинский CRNN-CTC кандидат из RESEARCH. TrOCR добавить только если первые варианты не дают разумного результата. Не выбирать победителя по README CER.

Вход — polygon-masked line, выход TranscriptionCandidate. Metrics CER/WER, отдельно ґ/є/і/ї/й/ё, mixed Latin/Cyrillic, confidence reliability, CPU latency/RAM. Initial target CER≤10% на собственном held-out line subset после настройки; при непрохождении оставить recognizer assistive с обязательной коррекцией. Per-character качество не скрывать средней CER.

Gate выбора: прошедшие rights/codec/installation → минимальный CER на validation при приемлемом memory/latency; test используется один раз для итогового отчёта. Все selected revisions фиксировать. Качество на modern notes — эксперимент E-06.

### II-04. Reconstruction proposals и ручная редактура данных

**Зависит:** II-00/II-02; HTR optional, corrected transcription можно ввести вручную. Файлы `learning/reconstruction.py`, graph models, correction operations, preview overlays; UI не требуется, правки через typed request files/CLI API.

Реализовать skeleton→junction graph→цепочки/циклы, ограниченные hypotheses (≤8 на region), confidence dimensions и manual stroke order. Alignment по исправленному тексту подключить как hint, не hard slicing. Ambiguous соединённое слово может публиковаться как лигатурный sample, если key ≤8 графем, иначе оставаться reference, не притворяться отдельными буквами.

Tests T-C03…T-C07: crossings, dots, retracing ambiguity, два порядка одной маски, несоответствие transcript, no unique trajectory. Метрики geometry vs raster и order vs настоящие traces раздельны. StyleBuilder принимает только reviewed candidates. Выход — персональный StylePack, проходящий те же I tests.

### II-05. Training/retraining и model registry

**Зависит:** II-01/II-03. Files datasets/training/evaluation modules, dataset snapshots, model candidate records, rollback workflow.

Разметка исправлений append-only; train job выбирает immutable approved annotations. Для одного recognizer фиксировать hyperparameter spec, preprocessing, charset, early stopping по validation CER, random seeds, hardware/env. Training interruption не повреждает production weights. Selection/retrain не запускается на каждую correction автоматически.

Приёмка T-D03/T-D05: CER нового model на held-out не хуже предыдущего более чем на 0.5 процентного пункта; число ошибок protected chars не увеличивается на том же фиксированном наборе; происхождение данных полностью прослеживается, rollback работоспособен, тестовые примеры не попадали в train. Для публикации нужна измеримая польза — снижение validation CER либо correction time, а не только прохождение допуска. Если нового качества нет, сохранить прошлый production model. Увеличение samples может улучшить coverage даже без ML.

### II-06. Исследовательский offline→online backend

Только после рабочего correction workflow. Отдельный InkSight env и E-07 compatibility/quality experiment. Сравнить на paired subset с простым skeleton+manual baseline. Преимущество должно измеряться временем ручных исправлений и качеством пригодного StylePack, а не только красивой картинкой.

Неуспех/неподдерживаемый CPU оставляет feature отключённой. Не переписывать ядро и не расширять scope MVP ради тренировки большой генеративной модели.

## 5. Этап III и точки расширения

| Пакет | Начинать когда | Контракт/проверка |
|---|---|---|
| III-01: несколько профилей/стилей | Есть второй реальный набор | StyleRepository + immutable refs, no cross-profile sample leak |
| III-02: contextual ligature selection | Данные показали необходимость сверх longest-match | Новый shaping algorithm_id, corpus compare, сохраняется ShapedWord |
| III-03: другой формат страницы/станок | Есть конкретный запрос и профиль | PageSpec/Backend contract suites; новые units/kinematics explicit |
| III-04: генеративный trajectory model | Собран достаточный online корпус | Backend выдаёт тот же IR, coverage/text fidelity и geometry validators обязательны |
| III-05: UI | Отдельное задание на интерфейс | Только Application/Correction/Machine services, экран сейчас не проектируется |

## 6. Ворота передачи между пакетами

I-01 data model нельзя менять в I-08 незаметно: требуется migration/ADR. I-03 style review нельзя заменить successful test fixtures. I-09 software release не включает I-H. II персонализация не зависит от hardware, а II-A не зависит от OCR. Все измерения будущего исполнения сохраняются рядом с версиями inputs; эта архитектурная документация сама не содержит выполненных benchmark результатов.
