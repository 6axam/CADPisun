# Исследование компонентов и технической реализуемости

Дополнительная проверка источников именно для связной украинской скорописи от
2026-10-13 и решение по авторскому пилоту вынесены в
[`docs/handwriting-pilot-research.md`](docs/handwriting-pilot-research.md).

Проверено 2026-10-12. Исследование чтением: GitHub REST metadata/tree/commits, конкретные исходники, PyPI metadata, официальные спецификации и публикации. Ничего не установлено и не запущено. «Есть тесты» означает наличие тестов в дереве, а не успешный запуск. Последний commit указан для default branch; `pushed_at` может отражать другие ветки и не доказывает обновление продукта. Issues не использованы как доказательство отсутствия ошибок.

Уровни: **S** — прочитана реализация ключевого участка; **D** — документация/модельная карточка; **M** — metadata. Для отклонённых направлений не проводился полный аудит всего репозитория. Оценки интеграции: малая — адаптер ограниченного формата; средняя — несколько компонентов и набор regression fixtures; высокая — смена архитектуры/данных/ML-окружения. Это не оценки в днях.

## 1. Пять исходных кандидатов

### 1.1 utrost/VHS — полезный архитектурный референс, не база форка

Ревизия [1dabbad575b0, 2026-09-23](https://github.com/utrost/VHS/commit/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29), последнее изменение — документация. На момент проверки репозиторий не archived. Исследованы assembler, requirements, дерево glyphs, план cursive joining. Уровень S/M.

[assembler.py](https://github.com/utrost/VHS/blob/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29/assembler/assembler.py) содержит GlyphLibrary, Typesetter, Renderer: JSON-варианты, greedy-поиск многосимвольного ключа, optical kerning, переносы и SVG. В `typeset_text` seed затрагивает и глобальный `random`; это нежелательная модель для параллельных независимых запросов нашей библиотеки. Наличие генерации SVG не даёт аппаратного IR или драйвера.

Критическое различие: [R2_CURSIVE_JOINING_PLAN.md](https://github.com/utrost/VHS/blob/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29/docs/R2_CURSIVE_JOINING_PLAN.md) имеет статус draft. В прочитанном assembler нет реализованного пути `connect-letters`. Предложенное соединение нельзя засчитать как поставленную функцию. В [glyphs/font1](https://github.com/utrost/VHS/tree/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29/glyphs/font1) присутствуют латинские/немецкие символы и лигатуры; полного UA/RU набора по дереву файлов не обнаружено. Unicode-ключ JSON сам по себе не доказывает покрытие.

Python 3.10+ по README, Linux предусмотрен. [requirements.txt](https://github.com/utrost/VHS/blob/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29/requirements.txt): PyYAML, Flask, необязательные CairoSVG/pypdf; версии снизу, не воспроизводимый lock. Классы импортируемы, но API и исходник объединены с приложением. Есть тесты assembler/CLI/server, их прохождение не проверялось.

[Лицензия AGPL-3.0](https://github.com/utrost/VHS/blob/1dabbad575b08e9e6417ef34dcd731f7c2a6cd29/LICENSE). Отдельное происхождение и условия каждого sample glyph не установлены. Решение: изучать подходы, разрешить в будущем импорт собственных VHS JSON через адаптер; не копировать код и sample font в MIT-ядро. Стоимость адаптера средняя; стоимость доведения форка до всех наших контрактов высокая.

### 1.2 niccolodevries/svg-handwriting-generator — не подходит для MVP

Ревизия [61544f003893, 2026-03-28](https://github.com/niccolodevries/svg-handwriting-generator/commit/61544f003893c99cbcb9013b33d0a437bbe1ac6f), переход TensorFlow → PyTorch; в доступной истории шесть коммитов. Уровень S/M. Python/Tkinter, модель Graves, геометрия и page export в [engine.py](https://github.com/niccolodevries/svg-handwriting-generator/blob/61544f003893c99cbcb9013b33d0a437bbe1ac6f/engine.py).

В [synth/drawing.py](https://github.com/niccolodevries/svg-handwriting-generator/blob/61544f003893c99cbcb9013b33d0a437bbe1ac6f/synth/drawing.py) словарь явно ограничен латиницей и несколькими знаками; нет кириллицы и прописных Q/X. `sanitize_text` заменяет Q/X строчными и пропускает неподдерживаемое. Это прямое нарушение сохранности нашего текста, а не косметическая проблема. Изменение Python-строки alphabet не научит checkpoint украинскому письму.

[README](https://github.com/niccolodevries/svg-handwriting-generator/blob/61544f003893c99cbcb9013b33d0a437bbe1ac6f/README.md) сам отмечает дефекты некоторых букв/стилей и длинных строк. Заявлены torch/numpy/scipy/svgwrite/matplotlib/Pillow, Linux возможен при наличии Tk. Визуальные тесты есть, независимого подтверждения качества нет. Репозиторий содержит weights и IAM style priming, но LICENSE в проверенном дереве отсутствует, API license = null. Отдельные права на модель/образцы также не подтверждены.

Решение: отклонить зависимость; оставить как пример online synthesis и ограничений словаря. Интеграция UA высокая: данные, обучение, лицензии, проверка текста. Никакие готовые веса не входят в продукт.

### 1.3 msurguy/cnc-text-tool — источник сравнения SVG-font workflow

Ревизия [9a7c1a047841, 2026-08-09](https://github.com/msurguy/cnc-text-tool/commit/9a7c1a047841e25a9b731547a0f4d019fc80709c): сайт перенаправлен на Plotter Text; это не свидетельство нового shaping engine. Уровень S/M. [package.json](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/package.json): React 19, Vite 7, svgpath 2.6, Zustand 5. Linux через браузер; Python API нет.

[fontLoader.js](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/src/react/utils/fontLoader.js) читает SVG glyph unicode/advance/path и меняет масштаб/ось. [textLayout.js](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/src/react/utils/textLayout.js) перебирает Unicode code points, размещает по advances и пропускает отсутствующие glyphs. Это не графемный shaping и не движок контекстных соединений. Название CNC не означает универсального G-code sender.

Проверен конкретный [HersheyCyrillic.svg](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/public/fonts/Hershey/HersheyCyrillic.svg): таблица unicode не содержит Ґ/ґ, Є/є, І/і, Ї/ї; полный требуемый украинский алфавит отсутствует. Название Cyrillic не является проверкой покрытия или скорописи. [EMSAllure.svg](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/public/fonts/EMS/EMSAllure.svg) содержит собственное указание SIL OFL.

Код [MIT](https://github.com/msurguy/cnc-text-tool/blob/9a7c1a047841e25a9b731547a0f4d019fc80709c/LICENSE), лицензии шрифтов индивидуальны. Решение: не переносить веб-приложение; использовать опубликованные форматы как fixtures только после проверки конкретного файла. Конвертер SVG font → наш StylePack имеет среднюю стоимость; подключение JS ради размещения символов не оправдано.

### 1.4 wardaoppal/Handwriting-Robot — обводка изображения, не восстановление письма

Ревизия [b2ede1d65cb6, 2026-08-15](https://github.com/wardaoppal/Handwriting-Robot/commit/b2ede1d65cb672309f8bf5b15a0a9fd30f1f20b2); три доступных коммита, исходники загружены одним коммитом. Уровень S/M. [handwriting_to_path.py](https://github.com/wardaoppal/Handwriting-Robot/blob/b2ede1d65cb672309f8bf5b15a0a9fd30f1f20b2/Hndwriting-Robot/handwriting_to_path.py): threshold → `findContours(RETR_LIST, CHAIN_APPROX_NONE)` → pen points. Контур представляет границу области чернил, не центральную траекторию. Длина-фильтр способен удалять значимые мелкие отметки; разметки букв/текста нет.

[path_to_gcode.py](https://github.com/wardaoppal/Handwriting-Robot/blob/b2ede1d65cb672309f8bf5b15a0a9fd30f1f20b2/Hndwriting-Robot/path_to_gcode.py) фиксирует размер по ширине рисунка, переворот Y, команды M3 S1000/M5 и скорости, возвращает инструмент в X0Y0. Ни механизм пера, ни безопасная достижимость этой позиции для нашего неизвестного станка из такого кода не следуют. Feed у G0 нельзя считать управлением скоростью rapid для любого диалекта.

Python, OpenCV/numpy/matplotlib, возможен Linux. Нет отделённой библиотеки, воспроизводимого набора зависимостей и явной лицензии в проверенном дереве. Решение: не использовать исходники; сохранить как отрицательный пример смешения контуров, штрихов и hardware assumptions. Для задачи копирования изображения это иной функциональный продукт.

### 1.5 jvolker/single-line-font-renderer — небольшой SVG font renderer с устаревшим стеком

Default branch [26a206672dd1, 2021-03-08](https://github.com/jvolker/single-line-font-renderer/commit/26a206672dd19dfc4ae2b1b0259183c1eda37700). API `pushed_at` был 2026-10-05, но последний commit этой ветки — 2021: в отчёте сопровождение оценивается по коду. Уровень S/M.

[svgFontRenderer.js](https://github.com/jvolker/single-line-font-renderer/blob/26a206672dd19dfc4ae2b1b0259183c1eda37700/src/lib/svgFontRenderer.js) адаптирован из hersheytextjs: XML glyph lookup, advances, path output. Рендер идёт по `word[i]`, то есть UTF-16 code units; нет нашего графемного/контекстного контракта, отсутствующие glyphs не вызывают требуемой ошибки. Импортируемые SVG fonts могут содержать Unicode, но это не равнозначно полному Unicode layout.

[package.json](https://github.com/jvolker/single-line-font-renderer/blob/26a206672dd19dfc4ae2b1b0259183c1eda37700/package.json): Vue 2.6.12, Vuetify 2.4.3, старый Vue CLI 4.5.11, Cheerio rc; [код MIT](https://github.com/jvolker/single-line-font-renderer/blob/26a206672dd19dfc4ae2b1b0259183c1eda37700/LICENSE). Шрифты не наследуют автоматически лицензию приложения. Браузер на Linux поддерживает сценарий, Python API нет. Решение: референс формата, не зависимость; перенос страницы целиком создаёт лишний JS-стек и не решает скоропись.

## 2. Дополнительные компоненты

### 2.1 Геометрия, шрифты, вёрстка и SVG

| Проект / доказательство | Реальная роль и ограничения | Решение |
|---|---|---|
| [svg.path parser](https://github.com/regebro/svg.path/blob/e63fb851a0bba51bf76f3006ef0d49913d93e7bf/src/svg/path/parser.py), [metadata](https://github.com/regebro/svg.path/blob/e63fb851a0bba51bf76f3006ef0d49913d93e7bf/pyproject.toml) | S: SVG path parser и классы кривых, MIT, без обязательных runtime dependencies; Python ≥3.8. HEAD 2026-07-07, стабильный PyPI 7.1, HEAD 7.2.dev0. Не парсер всего SVG DOM и не планировщик | Выбран для optional importer. Convert-on-boundary, стоимость малая. Не разрешать дуги/произвольные SVG effects только потому, что парсер их читает |
| [svgpathtools setup](https://github.com/mathandy/svgpathtools/blob/15b500ef3dc23336b114f40fb18d957483d3968f/setup.py) | S: MIT, Python ≥3.8, numpy/scipy/svgwrite обязательны; версия 1.8.0 в setup. HEAD 2026-10-07 включает fix пустого path d | Альтернатива для сложной геометрии и независимых тестовых oracle; не обязательная тяжесть MVP |
| [vpype](https://github.com/abey79/vpype/tree/7d47f39c45dd90e614aff3dcf76713a557c63051), [pyproject](https://github.com/abey79/vpype/blob/7d47f39c45dd90e614aff3dcf76713a557c63051/pyproject.toml) | D/S metadata: MIT, Python ≥3.11,<3.14 на HEAD 2026-10-07; numpy/scipy/Shapely, optional Qt/GL. Полилинии, SVG IO, просмотр, merge/sort. Сортировка/разворот теряют семантику письма | Отдельный необязательный инструмент инспекции; не canonical IR и не автоматический postprocessor handwriting |
| [Hershey Text](https://gitlab.com/oskay/hershey-text), [документация поставщика](https://wiki.evilmadscientist.com/Hershey_Text) | D: готовое преобразование engraving fonts в пути. Шрифтовые лицензии и происхождение проверяются по каждому файлу. Специальные stroke fonts отличаются от TTF contours | Референс и диагностические алфавиты, не обещание UA cursive. GitLab дерево в этой проверке полностью не доступно |
| [techninja/hersheytextjs](https://github.com/techninja/hersheytextjs) | D: JSON/SVG данные и JS renderer. Сам по себе не обучает стиль и не восстанавливает направление из фото | Рассмотрен, но собственный Python importer устраняет Node runtime; глубокий аудит не нужен для отклонённой зависимости |
| [Unicode UAX29](https://www.unicode.org/reports/tr29/), [UAX14](https://www.unicode.org/reports/tr14/) | D: графемы и допустимые точки переноса — разные задачи | regex для кластеров; ограниченный документированный LTR line-break policy, не заявление о полной реализации UAX14 |

Обычная font shaping библиотека, например HarfBuzz, полезна для OpenType typography, но не превращает fill-outline glyph в записанное движение пера. PDF/HTML layout engines также не решают порядок штрихов. Для одноформатного MVP собственный word-wrap меньше и прозрачнее полноценного издательского движка.

### 2.2 Запись пера и синтез

**utrost/Tracer**: [HEAD b530eb46328a, 2026-08-05](https://github.com/utrost/Tracer/commit/b530eb46328a2a8500a3fd13076c8dce90204b6e). [Capture format](https://github.com/utrost/Tracer/blob/b530eb46328a2a8500a3fd13076c8dce90204b6e/docs/capture-format.md) сохраняет px, слои, порядок, x/y/p/t; timestamp может быть абсолютным или относительным. [README](https://github.com/utrost/Tracer/blob/b530eb46328a2a8500a3fd13076c8dce90204b6e/README.md) предупреждает: pressure width SVG создаёт filled outline, тогда как JSON сохраняет центральные линии. Уровень D, raw capture app internals полностью не аудировались. [AGPL-3.0](https://github.com/utrost/Tracer/blob/b530eb46328a2a8500a3fd13076c8dce90204b6e/LICENSE). Рекомендован как отдельный существующий инструмент сбора **своих** данных, с импортом JSON, не как встроенный UI. Слои не считать глобальным временным порядком без проверенных timestamps.

**sjvasquez/handwriting-synthesis**: [HEAD 5f58984c3bc7, 2020-02-20](https://github.com/sjvasquez/handwriting-synthesis/commit/5f58984c3bc793bd8930bad7012cd2008d4a4a66); [requirements](https://github.com/sjvasquez/handwriting-synthesis/blob/5f58984c3bc793bd8930bad7012cd2008d4a4a66/requirements.txt) требует TensorFlow 1.6.0. Это историческая реализация [Graves 2013](https://arxiv.org/abs/1308.0850), полезная для понимания координат/pen-up output, но не поддерживаемый UA backend. Устаревшее окружение и англоязычные данные делают интеграцию высокой сложности. Права на отдельные checkpoint/style assets здесь не подтверждены; не распространять.

Для будущего захвата определены внешние стандарты [InkML](https://www.w3.org/TR/InkML/) и [Pointer Events](https://www.w3.org/TR/pointerevents3/). Они позволяют хранить каналы времени/давления, но наличие поля pressure не гарантирует реальный датчик; значение по умолчанию не интерпретировать как измерение силы.

### 2.3 CV и восстановление центральных линий

**OpenCV**: официальные [геометрические преобразования](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html) дают homography/warpPerspective. Код Apache-2.0 в современных версиях, Python wheels Linux; выбран headless 4.13.0.92 для будущего vision env. На PyPI уже есть 5.0.0.93, но обновление major не принято без тестов. Уровень D/M; это исправление перспективы плоского листа, не автоматическое выпрямление согнутой страницы.

**scikit-image**: [skeletonize](https://scikit-image.org/docs/0.26.x/auto_examples/edges/plot_skeleton.html) сохраняет топологический скелет маски, а не историю рисования. BSD-family с per-file notices; stable 0.26.0, Python ≥3.11. HEAD 2026-10-09. Выбран для II-B; morphology имеет риск удаления точек/разрыва тонких соединений. Отдельно проверять компоненты «ї/й/ё», а не только похожесть общей маски.

**LingDong-/skeleton-tracing**: [HEAD f5dd65e2389f, 2021-03-05](https://github.com/LingDong-/skeleton-tracing/commit/f5dd65e2389f9311dd3c24b9a83bd852c28c49e9), [Python implementation](https://github.com/LingDong-/skeleton-tracing/blob/f5dd65e2389f9311dd3c24b9a83bd852c28c49e9/py/trace_skeleton.py), [MIT](https://github.com/LingDong-/skeleton-tracing/blob/f5dd65e2389f9311dd3c24b9a83bd852c28c49e9/LICENSE). S: thinning + разделение изображения/соединение полилиний, numpy, optional skimage; C/SWIG ускорение отдельно. Нет временного ground truth. Не выбран как базовый реконструктор: нужен сохраняемый граф развилок и альтернативных порядков. Допустим benchmark против нашего небольшого graph adapter; стоимость адаптации средняя, качество на UA не известно.

**Potrace / AutoTrace**: [Potrace](https://potrace.sourceforge.net/) ориентирован на bitmap tracing; [AutoTrace](https://github.com/autotrace/autotrace) предоставляет в том числе centerline-направление. Это векторизация, не HTR и не восстановление оригинального времени. Не используются в MVP. Автотрассировка не заменяет проверку центральной линии и правил stroke ordering; лицензии C-компонентов проверять перед отдельным внедрением, не смешивать с permissive Python core.

### 2.4 HTR и модели

**Kraken выбран как основной обучаемый HTR/segmentation backend этапа II**, а не как готовая модель почерка пользователя. Проверенная ревизия: [HEAD bb487219e7d8, 2026-10-12](https://github.com/mittagessen/kraken/commit/bb487219e7d8289274443d1ad0989efb4924dc2a).

[pyproject](https://github.com/mittagessen/kraken/blob/bb487219e7d8289274443d1ad0989efb4924dc2a/pyproject.toml) и [align.py](https://github.com/mittagessen/kraken/blob/bb487219e7d8289274443d1ad0989efb4924dc2a/kraken/align.py) прочитаны: Apache-2.0, PyTorch/Lightning, segmentation/recognition/training, forced alignment API меняется. HEAD рекомендует `ForcedAlignmentTaskModel` вместо legacy `forced_align`. Stable [PyPI 7.1.1](https://pypi.org/project/kraken/7.1.1/) ограничивает Python <3.14 и skimage ~0.25.2/scipy ~1.15.3. Нельзя смешивать этот stable lock с зависимостями main. Уровень S/M, запуск не проводился. Linux ориентирован, CPU inference возможен; скорость на ThinkPad не измерена. Unicode codec модели должен включать нужные символы; название multilingual этого не доказывает. Интеграция средняя/высокая, отделена JSON job boundary.

**TrOCR**: [microsoft/trocr-base-handwritten](https://huggingface.co/microsoft/trocr-base-handwritten) — line-level IAM checkpoint, card MIT, PyTorch/Transformers. Уровень D. Не готовое доказательство качества UA. Запланирован как сравнительный recognizer только если Kraken не проходит локальную приёмку. Не использовать старые примеры pipeline без проверки версии Transformers.

**Украинские кандидаты для сравнительного теста**:

- [achimrabus/crnn-ctc-ukrainian](https://huggingface.co/achimrabus/crnn-ctc-ukrainian): card Apache-2.0, CRNN/CTC исторических UA документов; собственный PyTorch формат, не PyLaia package checkpoint. Требует polygon-masked line crops; автор сообщает заметное падение качества при прямоугольном crop. Авторские CER не переносим на конспекты. Код inference связан с polyscriptor; интеграция отдельным адаптером, лицензия upstream training data ещё подлежит проверке.
- [Valerii02/ukr-htr-convtext](https://huggingface.co/Valerii02/ukr-htr-convtext): card заявляет украинское распознавание и custom model code. Кандидат, не выбранный компонент. Полный аудит весов, кода и разрешений не выполнен; автоматическое `trust_remote_code` запрещено контрактом model loading. Не принимать рекламируемую таблицу сравнений за собственный benchmark.
- [Tesseract FAQ](https://github.com/tesseract-ocr/tesseract/wiki/FAQ): базовый печатный OCR не выбран для связной рукописи. Может позже помогать с печатными заголовками; это отдельный сценарий.

### 2.5 Offline → online: реальные результаты и пределы

**InkSight**: [code HEAD 486d4772e2fd, 2026-07-29](https://github.com/google-research/inksight/tree/486d4772e2fdd187f0c3416a41479b1ffc080c66), [pyproject](https://github.com/google-research/inksight/blob/486d4772e2fdd187f0c3416a41479b1ffc080c66/pyproject.toml), [TensorFlow compatibility utility](https://github.com/google-research/inksight/blob/486d4772e2fdd187f0c3416a41479b1ffc080c66/utils/tensorflow.py). Code Apache-2.0, [Small-p card](https://huggingface.co/Derendering/InkSight-Small-p) также Apache-2.0. HEAD требует TF 2.20.0/text 2.20.1 с совместимостью XLA, card всё ещё предупреждает о версиях выше 2.17. Уровень S/D: зафиксировано **расхождение источников**, а не доказанная совместимость. Пакет включает CUDA extras, которые нельзя считать подходящими AMD ноутбуку.

[Публикация](https://arxiv.org/abs/2402.05804) показывает возможность правдоподобного derendering, но не восстановление истинной истории каждого слова. Публичный [набор derenderings](https://github.com/google-research/inksight/blob/486d4772e2fdd187f0c3416a41479b1ffc080c66/docs/dataset.md) содержит модельные InkML outputs; их нельзя маркировать как записанные человеком траектории. Интеграция высокая; только эксперимент II-C, без зависимости MVP.

[TRACE](https://arxiv.org/abs/2105.11559) и [ordered stroke instance prediction 2026](https://arxiv.org/abs/2609.02251) подтверждают исследовательские подходы к line/stroke recovery. Последняя работа прямо рассматривает неоднозначность порядка/направления. Полная воспроизводимость, лицензированные weights и качество на UA здесь не подтверждены. Не назначать их обязательной технологией.

Инженерный вывод: разные порядки обхода, направления и повторные проходы могут дать одинаковый raster. Проекция many-to-one; точное обратное восстановление без дополнительных данных в общем случае невозможно. Confidence должен быть раздельным для текста, геометрии и порядка, с возможностью unknown.

### 2.6 Motion / G-code / транспорт

| Компонент | Проверка | Решение |
|---|---|---|
| [vpype-gcode gwrite.py](https://github.com/plottertools/vpype-gcode/blob/dce64e24fdaec85f879fb13aa2db86ee64c96797/vpype_gcode/gwrite.py), [setup](https://github.com/plottertools/vpype-gcode/blob/dce64e24fdaec85f879fb13aa2db86ee64c96797/setup.py) | S; HEAD 2025-09-01, MIT metadata, vpype ≥1.10,<2, click/numpy; формат задаётся document/line/segment templates | Референс профилей, не validator аппаратной семантики. Самостоятельный маленький emitter проще проверять; средняя интеграция |
| [pySerial](https://github.com/pyserial/pyserial/tree/a5c48d445fbc1943d4fabf8d9090a50fda3172fd), [LICENSE](https://github.com/pyserial/pyserial/blob/a5c48d445fbc1943d4fabf8d9090a50fda3172fd/LICENSE.txt) | M/D; stable 3.5, BSD-3-Clause, HEAD 2026-02-27; Linux serial, нет собственного CNC flow control | Выбран для I-H serial transport; поверх — наш protocol state machine. Порт не открывается при импорте |
| [GRBL v1.1 Interface](https://github.com/gnea/grbl/wiki/Grbl-v1.1-Interface), [commands](https://github.com/gnea/grbl/wiki/Grbl-v1.1-Commands), [planner.c](https://github.com/gnea/grbl/blob/master/grbl/planner.c) | S/D: буфер, ответы, real-time status; motion look-ahead в firmware; GPL-3.0 в source headers | Референс одного диалекта, не назначение платы. `ok` не означает завершение движения. Не переносить planner.c в Python |
| [FluidNC](https://github.com/bdring/FluidNC/tree/768b0c96a725f4e468dbc9e76a285473c201c2fe) | M/D; HEAD 2026-10-12, конфигурируемая firmware, отдельная аппаратная экосистема | Возможный будущий профиль только после выбора электроники; никакого обязательного ESP32 |
| [Universal Gcode Sender](https://github.com/winder/Universal-G-Code-Sender) | D: отдельное cross-platform приложение для нескольких контроллеров | Разумная альтернатива своему sender на первом реальном стенде; не Python runtime dependency. Точная совместимость/лицензия дистрибутива проверяется при выборе версии |
| [LinuxCNC G-code reference](https://linuxcnc.org/docs/stable/html/gcode/overview.html) | D: диалект с собственными modal semantics | Основание явно разделять диалекты, а не обещать универсальный G-code |

Исторический `grbl/grbl` с HEAD 2021-01-23 не следует путать с документацией `gnea/grbl` v1.1. В проекте фиксируется identity firmware, версия и подтверждённый набор команд.

## 3. Датасеты

| Источник | Полезные данные | Ограничение и применение |
|---|---|---|
| [IAM-DB / IAM-OnDB](https://fki.tic.heia-fr.ch/databases), [online format](https://fki.tic.heia-fr.ch/DBs/iamOnDB/data.html) | Английский raster/text и записанные x/y/time в OnDB | Non-commercial research условия поставщика; не распространять по умолчанию. Benchmark методики, не UA корпус |
| [HKR](https://github.com/abdoelsayed2016/HKR_Dataset) | Русский/казахский offline text | CC-BY-NC-ND-4.0 файл и отдельная заявка по README. Не считать готовым свободным обучающим набором UA или online trajectories |
| [InkSight Derenderings](https://huggingface.co/datasets/Derendering/InkSight-Derenderings) | Предсказанные цифровые штрихи нескольких систем | Отдельно проверять права исходных изображений; использовать как pseudo-label, не истинный порядок |
| Собственный набор проекта | UA/RU/EN, фото, транскрипции, настоящие записи пера, согласие автора | Основной production источник. Хранить provenance, consent, разделять сессии train/validation/test; объёмы и протокол в IMPLEMENTATION_PLAN |

Поиск также выявил новые UA корпуса/карточки; ни один не был признан обязательным без проверки происхождения. Основная архитектура не зависит от доступности внешнего dataset URL.

## 4. Что берём и что создаём

| Компонент | Готовое решение | Собственная реализация | Необходимая доработка | Причина выбора |
|---|---|---|---|---|
| Валидация DTO | Pydantic | Инварианты штрихов/координат | Strict models, ошибки предметной области | Не писать framework сериализации |
| Графемы | regex | NFC/source map/политика breaks | Привязка к версиям Unicode | Сохранить диакритики |
| SVG path import | svg.path + defusedxml | Ограниченный документированный importer | Порядок subpaths, единицы, glyph metadata | Не тащить JS renderer |
| Почерк | Авторские центральные линии / Tracer как внешний инструмент | StylePack, UA графемы, вариантность | Entry/exit и pair fixtures | Главная непокрытая готовыми решениями задача |
| Соединения/строки | Нет подходящего проверенного UA движка | Shaping, правила joins, greedy layout | Проверенный набор букв и тестов | Сохранить текст и семантику |
| Stroke math | stdlib; svgpathtools как возможный oracle | Небольшой набор Bézier операций и PenPlan | Ограниченные типы и погрешность | Полный контролируемый IR |
| SVG | stdlib XML writer | Прямой экспорт M/L/Q/C | Preview metadata отдельно | Нет зависимости от шрифта в просмотрщике |
| G-code | Документация выбранной firmware | Typed dialect emitter/decoder | Pen capabilities и handshake | Нужна проверяемая семантика |
| Serial | pySerial | Состояния sender/flow control | Один реальный протокол после выбора станка | Изоляция железа |
| Image cleanup | OpenCV/skimage | Pipeline config и provenance | Маски и ручные правки | Проверенные CV примитивы |
| HTR | Kraken; альтернативы по benchmark | Адаптер/реестр моделей | Собственный codec и дообучение | Не переизобретать распознавание |
| Реконструкция | skimage skeleton, исследовательские модели optional | Граф гипотез и correction workflow | Неоднозначные развилки/порядок | Изображение не содержит историю |
| Хранение | JSON, SQLite stdlib | Репозиторий immutable revisions | Атомарность/миграции | Без инфраструктуры |

## 5. Итог проверки оснований

Подтверждено исходниками/документацией: stroke-based хранение, SVG path parsing, CPU геометрия, CV rectification/skeletonization, локальный HTR и профильная CNC коммуникация имеют готовые строительные блоки.

Предположительно реализуемо: естественный `ua-school-v1`, контекстные joins и предсказуемая скорость на конкретном ноутбуке. Это проектные гипотезы до экспериментов.

Открыто: гарантированное качество персонального почерка из случайных фото; точная история штрихов; совместимость с неизвестным станком. Эксперименты и критерии в [RISKS.md](RISKS.md). Неуспех этих направлений не требует менять IR или терять работоспособный этап I.
