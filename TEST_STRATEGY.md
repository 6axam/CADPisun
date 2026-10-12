# Проверки, критерии приёмки и трассируемость

v1.0 · Это **спецификация будущих тестов**, не отчёт об их успешном выполнении. Сейчас выполнен только документарный аудит в §7. Источники технических оснований — [RESEARCH.md](RESEARCH.md), эксперименты — [RISKS.md](RISKS.md).

## 1. Уровни проверки и тестовые данные

1. Unit/property: curves/frames, Unicode, deterministic selection, state machines, validation.
2. Adapter contracts: SVG parsing, model IO, dialect decode, fake transport; без оборудования.
3. End-to-end software: text→StylePack→Page→PenPlan→MotionPlan→export→independent decode.
4. Визуальная/лингвистическая приёмка: реальные читаемые glyphs и соединения, не только golden hashes.
5. Physical HIL: только после профиля/калибровки, отдельно от CI.

Fixtures собственные, с разрешёнными данными. Golden outputs сохраняются вместе с seed, style hash, runtime/algorithm/export versions. При намеренном изменении алгоритма golden обновляют только после semantic diff: потеря буквы не маскируется массовой перезаписью snapshots.

Обязательный корпус включает полный UA/RU/EN алфавит обоих регистров, digits/punctuation, NFD-equivalent ї/й/ё, apostrophe variants, смешанный язык и реальные слова из I-03. Добавить уникальный идентифицируемый token на каждом ожидаемом page boundary. Генерированные тестовые строки — для инвариантов, реальные слова — для читаемости.

Проверка coverage сравнивает source mapping, а не OCR generated image: renderer не должен полагаться на внешний recognizer для доказательства того, что не потерял исходный текст.

## 2. Реестр software tests

### Геометрия и модели

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-G01 | Line/Q/C с внутренними экстремумами | Bounds содержат всю кривую, совпадают с независимыми аналитическими fixtures в tolerance |
| T-G02 | Cubic loop, P0=P3, отдалённые controls | Flatten не превращает loop в точку, error≤0.02mm |
| T-G03 | NaN/Inf/огромные числа/несовпадающие endpoints | Validation failure до экспорта, не зависание и не частичный output |
| T-G04 | Scale/translation/shear/reflection и обратное преобразование | Round-trip≤1e-9 от характерного масштаба в адекватном диапазоне; frame mismatch отклонён |
| T-G05 | Property generation curves + resource budgets | Сохраняются направление, endpoints, порядок; bound не превышен или явный failure |
| T-G06 | Loop/junction/critical short marks и collision distance | Запрещённый контакт обнаружен; authored self-crossing не удалён; terminal mark сохранён |

Не проверять flatten только равномерными samples той же функции: нужна conservative error bound, fixtures с экстремумами и независимый oracle в ограниченном dev suite.

### Unicode и стили

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-U01 | Все обязательные glyphs из DATA_MODELS | 100% coverage и source mapping, без замен |
| T-U02 | `ґ є і ї Ґ Є І Ї`, й/ё в NFC/NFD | Эквивалентная форма, правильные critical marks, исходные spans сохранены |
| T-U03 | `І I і i а a`, UA/EN/RU в строке | Разные Unicode keys не смешаны; script joins запрещены |
| T-U04 | `' ’ ʼ`, кавычки, NBSP/U+202F, tab, LF/CRLF/form-feed | Нормативные token/break semantics без лишней ink |
| T-U05 | Emoji/RTL controls/неподдерживаемая combining sequence | Все позиции перечислены; production bundle не опубликован |
| T-U06 | Пустой, whitespace-only, input limit и source mapping после NFC | EMPTY_DOCUMENT/RESOURCE_LIMIT либо полный корректный документ; нет усечения |
| T-S01 | Style version/hash/duplicate keys/bad anchors | Неверный пакет отклонён, error адресует объект |
| T-S02 | Реальный ua-school-v1 | Каждая строчная ≥3 approved variants, прочие required≥1, rights/coverage/review complete |
| T-S03 | SVG M/subpaths/Z/Q/C/transforms | Stroke direction/order/units не потеряны; unsupported A/CSS/use rejected |
| T-S04 | DTD/entities/external refs/path traversal | Нет network read/выхода из package; контролируемый отказ |
| T-S05 | Publish interruption/stale parent/unknown major | Старая revision работоспособна, новая либо полная, либо отсутствует |

### Shaping, соединения и случайность

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-J01 | Проверенная join pair после scale/slant/offset | Общие endpoints, G1 tangent direction, valid clearance |
| T-J02 | Space/apostrophe/punctuation/script boundary | 0 connectors через запрещённые границы |
| T-J03 | Pair с collision/обратным tangent/огромным gap | Controlled lift/retry или содержательная style error; нет произвольной линии |
| T-J04 | Строки `її`, `йой`, `minimum`, multi-stroke capitals | Каждая critical mark ровно один раз, authored/deferred order соблюдён |
| T-J05 | Лигатура longest match и context eligibility | Покрытие source ranges точное, при split возможна корректная de-ligation |
| T-J06 | Оптимизация forbidden order/reversal | Запрос неподдерживаемой reorder политики отклонён, stroke IDs сохраняют порядок |
| T-J07 | Pair corpus всех anchor classes/исключений | Все approved pairs проходят geometry; rejected/exception объяснены и визуально приняты |
| T-R01 | Одинаковый seed/input/lock в двух независимых процессах | Canonical plan/SVG/G-code bytes идентичны; audit timestamps исключены |
| T-R02 | Разные seed и repeated letters | Варианты различаются при наличии выбора, никогда нет чтения global random state |
| T-R03 | Повторное measurement, изменение полей, fragmentation | Исходные glyph occurrence choices стабильны, boundary variants меняются только по правилам context |

### Вёрстка и pen state

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-L01 | Строка ровно у правого поля, negative bearing/curved tail | Вся ink envelope внутри printable rectangle |
| T-L02 | Многострочный и 10-страничный corpus | Все source spans ровно один раз, правильные page IDs/order |
| T-L03 | Oversized token/одна большая графема | Emergency split по clusters либо GLYPH_TOO_WIDE; не half-glyph |
| T-L04 | Лигатура/апостроф/closing punctuation у разрыва | Корректный reshape и punctuation attachment, без лишнего дефиса |
| T-L05 | NBSP group шире страницы, explicit page breaks | NONBREAKABLE_OVERFLOW; page-break policy точно соблюдён |
| T-L06 | Ascenders/descenders/marks при малом requested pitch | Effective pitch увеличен, ни одной межстрочной коллизии |
| T-L07 | 100 seeds на boundary corpus, min/max accepted size | Все bounds проходят после variations; неисправимый случай явно отвергнут |
| T-P01 | Несколько strokes и words с одинаковыми endpoints | Travel только UP, draw DOWN, ни одного случайного соединения |
| T-P02 | Start/end/отмена логической компиляции | План начинается UP request, завершает страницу UP; incomplete не публикуется |
| T-P03 | Body chains и deferred marks | Порядок соответствует schedule, ни потерь, ни повторов |
| T-P04 | Попытка отправить diagnostic preview | Тип/role отвергается production motion path |

### SVG, команды и motion

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-E01 | SVG parse независимым XML reader | Well-formed, только allowed elements/paths, физический viewBox/mm |
| T-E02 | Сравнение SVG paths с PenPlan | Число контактов/геометрия/source IDs согласованы, travel отсутствуют |
| T-E03 | Спецсимволы текста и XML metadata | Нет XML injection/внешних ресурсов; текст как данные |
| T-E04 | Virtual commands independent decoder | Geometry и pen state эквивалентны MotionPlan в ≤0.05mm |
| T-E05 | G20/G91/неизвестный M-code/NaN/injected newline | Отклонено, modal state не игнорируется |
| T-E06 | mm/s→mm/min, Z/XY feeds, G4 units | F точно ×60, каждый требуемый settle сохранён |
| T-E07 | Финал файла и разные страницы | Перо UP, нет автоматического unsafe home/park или сквозной смены листа |
| T-M01 | Page→Work flip/rotation/translation | Известные контрольные точки и ориентация правильны |
| T-M02 | Initial/travel/draw/Z/park за лимитом | Каждый выход обнаружен, даже если ink помещается на листе |
| T-M03 | No-go region на прямом pen-up travel | Отказ; через крепление не проводится «невидимый» ход |
| T-M04 | Quantization у границы и critical tiny stroke | Повторная проверка; не исчезает вся mark, иначе RESOLUTION_INSUFFICIENT |
| T-M05 | Unknown origin, unsupported kinematics, pen synchronization | Export/send gate по нужному уровню, никаких guessed defaults |
| T-M06 | Profile/registration hash изменился после prepare | PreparedJob invalid, новое preflight обязательно |
| T-M07 | Timing reports | Lower bound включает длины и dwells; точная физическая ETA не заявляется |

### Application и аппаратный протокол

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-A01 | Чистая установка/base import | Без CV/ML/serial и сети при генерации |
| T-A02 | Ошибка буквы в конце документа, disk-full, cancel | Не опубликован completed bundle, прежние файлы не повреждены |
| T-A03 | Полный software acceptance corpus | TXT→multi-page SVG/virtual G-code/планы/reports, одинаковые hashes при повторе |
| T-A04 | Performance и limits | 20k graphemes/10 pages target≤30s,≤512MiB на описанном host; limits fail fast |
| T-H01 | Fake serial partial writes/fragmented reads/status interleaving | Ответы правильно собраны, unsent bytes не потеряны |
| T-H02 | `ok` до завершения движения | Статус не completed до drain/idle/final check |
| T-H03 | Timeout после возможного исполнения, disconnect | Движение не retry автоматически, job Faulted |
| T-H04 | Alarm/hold/resume/reset | State machine по ARCHITECTURE; позиция после reset unknown до подтверждения |
| T-H05 | Simulation artifact/firmware mismatch | Start запрещён до любого motion write |
| T-H06 | Replay journal/checkpoints и смена страницы | last_accepted≠last_executed; unsafe resume блокирован |

### CV/HTR/персонализация

| ID | Сценарий | Условие успеха |
|---|---|---|
| T-C01 | Perspective flat page, EXIF, known corners | Inverse maps согласованы; image processing не перезаписывает original |
| T-C02 | Shadow/rules/low contrast/curved page | Предложения и masks inspectable; critical dots не удалены молча; curved case flagged |
| T-C03 | Cursive connected word и disconnected letter marks | Не навязано «component=character», доступны ligature/alternative segmentation |
| T-C04 | HTR исправление и forced alignment | Исправленный текст сохранён отдельно от prediction; alignment uncertainty видна |
| T-C05 | Crossings, cycles, одинаковый raster двух порядков | ≥2 hypotheses либо unresolved; не выдумана historical certainty |
| T-C06 | Geometry raster overlay и online ground truth | Geometry/order metrics разделены; smooth не уничтожает critical features |
| T-C07 | Непринятый candidate/новый model checkpoint | Не попадает в production StylePack/ModelRegistry |
| T-D01 | Online import x/y/t/pressure | Units/time basis/order сохранены; default pressure не назван силой |
| T-D02 | Correction concurrent edits/rollback | Append-only events, stale revision rejected, атомарность |
| T-D03 | Dataset split и повторные crops одной страницы | Ни одного source/session leak между train/test |
| T-D04 | Новая style revision | Старый render воспроизводится по старой revision, новая доступна явно |
| T-D05 | Training/model promote/rollback | Права/codec/hashes/env/evaluation проверены, production сохраняется при failed candidate |

## 3. Визуальная и лингвистическая приёмка

**V-01, читаемость.** Минимум1000 символов связного текста и отдельный полный alphabet sheet, включая lowercase confusables и protected UA letters. Не менее3 читающих соответствующий язык людей независимо переписывают текст без просмотра исходника. Цель ≥98% character agreement с исходником на корпусе и отсутствие систематической путаницы ґ/г, є/е, і/и/ї, й/и. Считать отдельно punctuation и script confusables. Это продуктовая цель, не опубликованный результат.

**V-02, естественность.** Сравнить 20 повторяющихся слов/строк с авторскими reference samples в том же размере. Median экспертной оценки связности/интервалов/форм ≥4 из5; все видимые дефекты pairs исправлены либо описаны как explicit pen lift. На заранее frozen корпусе допустимых связей минимум90% соединений действительно выполняются; нельзя уменьшить corpus/allowlist после неудачи ради процента. Для естественно несоединяемых прописных/пунктуации процент не применяется. При провале пересматривается data pack, не добавляется шум.

Дополнительно проверить min/max принятого размера, три seed, масштабы SVG 100% и увеличенный вид. Один красивый образец не доказывает качество многостраничного конспекта. Для model synthesis будущих этапов вводится отдельный текстовый fidelity gate: визуальная привлекательность не оправдывает неправильные буквы.

## 4. Метрики этапа II

- CER=(замены+удаления+вставки)/длина ground-truth Unicode text после общей NFC policy; WER тем же edit-distance принципом по документированной word segmentation. Считать микро-average, результаты по языку/автору/сессии и protected chars, а также raw и corrected text отдельно.
- Segmentation: precision/recall/F1 строк при polygon IoU≥0.5 плюс reading-order correctness и критические missed lines. Initial target F1≥0.95 на flat-page pilot; сложные страницы остаются с review.
- Reconstruction geometry: symmetric distance между rendered candidate centerline/ink и ground-truth, mask IoU/Chamfer при фиксированном raster resolution и pen width; цель после ручного review — без missing/extra critical components, median centerline distance≤1px в нормализованном оценочном crop.
- Order: stroke count, pen-up placement, direction accuracy и ordering distance/DTW **только** на paired online data. Resampling/normalization фиксировать, иначе DTW сравнения бессмысленны. Для фото без ground truth order_accuracy=null.
- Practical utility: медианное время correction/word и число rejected candidates, отдельно для manual baseline и автоматизации. Принятие сложного ML backend оправдано минимум25% снижением времени правок на frozen paired subset без ухудшения текста/critical features.
- Confidence reliability: risk-coverage curve / calibration bins для calibrated scores. Heuristic score не маркируется probability. Автоматическая публикация samples не включается даже при высоком score на pilot.

Порог CER≤10% — initial assistive HTR target, не разрешение печатать ошибочный текст: для наполнения обучающих данных обязательна проверка транскрипций. Data volume увеличивается по learning curves и error taxonomy.

## 5. Что можно и нельзя проверить без станка

| Проверка | Без оборудования | Только с оборудованием |
|---|---|---|
| Unicode, порядок, страницы, joins, source coverage | Полностью | Читаемость на бумаге дополнительно |
| SVG/XML и typed G-code subset | Полностью для объявленного dialect | Реальная интерпретация firmware/version |
| Координатные limits | По заявленному профилю | Соответствие профиля travel/креплениям |
| Pen transitions/settle commands | Логика и очередность | Фактический контакт/время/залипание |
| Feeds/acceleration | Requested limits и модель | Пропуски шагов, вибрация, угол, бумага |
| Время | Lower bound/условная оценка | Реальное время/чернила/длительные задания |
| Потеря связи | Fake state machine | Поведение платы, watchdog, emergency stop |
| Registration | Математика преобразования | Точность крепления, scale/skew/backlash |

H-A: pen-up dry run и контрольные точки; H-B: цикл100 подъёмов/опусканий на разрешённом профиле, без случайных ink travel; H-C: command/firmware compliance и pause/abort; H-D: минимум3 страницы UA/mixed текста, измерение отклонений, scans и полный job journal. Эти испытания не выполнялись в архитектурной задаче.

## 6. Матрица трассируемости требований

Требования ниже разложены из пользовательского задания на проверяемые единицы. «I-H» не скрыт внутри software MVP; future требования привязаны к соответствующим gates.

| Req | Требование | Модуль / способ | Этап | Приёмка |
|---|---|---|---|---|
| R01 | Начать заново без старого прототипа | Собственный package/IR, ADR-01 | I-00 | Не используются недоступные исходники |
| R02 | Python, Linux, локально | Base venv / CLI / files | I-00 | T-A01 |
| R03 | Минимум зависимостей/бесплатные технологии | Два core packages, optional adapters | I-00 | TECH_STACK и installation report |
| R04 | Произвольный поддерживаемый текст | text + style coverage | I-04 | T-U01/T-U05, нет фиксированного словаря фраз |
| R05 | Unicode | NFC/extended graphemes/source map | I-04 | T-U02/T-U03/T-U06 |
| R06 | Полный UA alphabet | explicit StylePack coverage | I-03 | T-S02/T-U01 |
| R07 | Полный RU alphabet | explicit union coverage | I-03 | ё/ъ/ы/э в T-U01/T-U02 |
| R08 | Полный EN alphabet | explicit coverage, включая Q/X | I-03 | T-U01/V-01 |
| R09 | ґ/є/і/ї, uppercase/lowercase | critical features и distinct keys | I-03/04 | T-U02/V-01 |
| R10 | Цифры и пунктуация | exact coverage manifest | I-03 | T-U01/T-U04 |
| R11 | Один готовый рукописный стиль | Authoring + review + package assets | I-03 | V-01/V-02, не test-only glyphs |
| R12 | Связная скоропись | anchors/classes + connectors + schedule | I-05 | T-J01/T-J07/V-02 |
| R13 | Контекстные формы/лигатуры | context variants, trie longest-match | I-05/III-02 | T-J05 |
| R14 | Варианты повторных букв | ≥3 lowercase variants + bounded selection | I-03/05 | T-S02/T-R02 |
| R15 | Естественные интервалы | authored advances/pair spacing/word space | I-05/06 | V-02/T-L01 |
| R16 | Размер букв | x-height mm, validated style range | I-05 | T-L07/V-01 |
| R17 | Наклон/размер/baseline variation | whole-glyph transforms до joins | I-05 | T-J01/T-R03 |
| R18 | Seed/repeatability | versioned hash-variation | I-05/09 | T-R01 |
| R19 | Читаемость, без случайного шума | bounds/critical features + review | I-03/05 | V-01/V-02 |
| R20 | A4, поля, межстрочные интервалы | PageSpec + measured layout | I-06 | T-L01/T-L06 |
| R21 | Перенос и несколько страниц | word wrap + grapheme fallback + pagination | I-06 | T-L02…T-L05 |
| R22 | Предпросмотр | Обычный и diagnostic SVG | I-07 | T-E01/V-01 |
| R23 | Одноштриховый SVG | Прямой экспорт ordered contacts | I-07 | T-E02/T-E03 |
| R24 | G-code | Typed per-dialect emit/decode | I-08/I-H | T-E04…T-E07; H-C |
| R25 | Симуляция без станка | Pen/Motion/command simulation layers | I-07/08 | T-P/T-M/T-A03 |
| R26 | Безопасные поднятые переходы | PenPlan FSM + synchronized backend | I-07/I-H | T-P01/H-B |
| R27 | Нет соединений между словами | Mandatory lift / no join boundary | I-05/07 | T-J02/T-P01 |
| R28 | Не выходить за лист | Полные ink bounds после transforms | I-06 | T-L01/T-L07 |
| R29 | Общая модель trajectories | Line/Q/C + ordered Stroke + PenPlan | I-01/07 | T-G/T-P |
| R30 | Масштабирование/frames/units | Typed Affine2/explicit mm/gu | I-01/08 | T-G04/T-M01 |
| R31 | Происхождение/версии | Style/asset/revision hashes | I-02/II-00 | T-S05/T-D04 |
| R32 | Совместимость standard/personal | Общий StylePack и shaper | II-00/04 | Те же I acceptance tests |
| R33 | Неизвестный hardware | Profile/registration/backend separation | I-08/I-H | T-M05, virtual не выдаётся за реальный |
| R34 | Несколько моделей станка | Backend ports, capability gate | I-H/III-03 | Один contract suite на backend |
| R35 | Скорость/ускорение/подъём | Profile, feed limits, firmware planner | I-H | T-M/H-B/H-D |
| R36 | CNC communication | pySerial + protocol state machine | H-01 | T-H01…T-H06 |
| R37 | Проверки/diagnostics | Structured errors/preflight/reports | I-01…09 | Все failure fixtures адресуют причину |
| R38 | Фото/сканы/отдельные буквы | SourceAsset/regions import | II-00/02 | T-C01/T-C03 |
| R39 | Online capture с временем | Tracer/InkML importer | II-00 | T-D01 |
| R40 | Perspective/background/noise | OpenCV/skimage pipeline | II-02 | T-C01/T-C02 |
| R41 | Строки и слова | Segmentation/HTR/alignment proposals | II-02/03 | T-C03/T-C04 |
| R42 | Распознавание текста | Kraken port/model registry | II-03 | CER/WER/per-char gate |
| R43 | Символы и связанные элементы | Region graph + optional ligatures | II-04 | T-C03/T-C05 |
| R44 | Ручная коррекция | Typed corrections, immutable revision | II-00/04 | T-D02/T-C04 |
| R45 | Геометрия из изображения | Skeleton graph + reviewed candidates | II-04 | T-C06/E-08 |
| R46 | Неизвестный порядок/направление | Alternatives + nullable confidence | II-04 | T-C05, не historical certainty |
| R47 | Несколько samples одного glyph | StyleBuilder/variant refs | II-00/04 | T-S02/T-D04 |
| R48 | Персональные соединения | Reviewed anchors/pair captures | II-04 | T-J07 на новом профиле |
| R49 | Улучшение по новым samples | Revision publish, explicit retrain | II-05 | T-D04/T-D05 |
| R50 | Несколько user profiles | Namespaced IDs/catalog/revisions | II/III-01 | No cross-profile sample leak |
| R51 | Persistent storage | Files I, SQLite+blobs II | I-09/II-00 | T-A02/T-D02 |
| R52 | GUI позже, API сейчас | Application/Correction services | I-09/III-05 | Контракты без экранов и toolkit |
| R53 | Изоляция ML | Отдельные envs/jobs | II-02/03/06 | Base import без torch/TF |
| R54 | Reuse вместо переписывания | Parsers/CV/HTR/serial + domain core | Все | RESEARCH table/TECH_STACK |
| R55 | Реальный анализ пяти кандидатов | Code/commit/license review | Архитектура | RESEARCH §1, source permalinks |
| R56 | Дополнительные проекты/датасеты | Primary sources и пригодность | Архитектура | RESEARCH §§2–3 |
| R57 | Лицензии кода/шрифтов/weights | Separate rights records | I-02/II-03 | T-S01/T-D05 |
| R58 | Сравнить A/B/C | ADR-01 + integration choices | Архитектура | DECISIONS и RESEARCH §4 |
| R59 | Без циклов, заменяемые модули | domain ports и DAG | I-00… | Import layering audit |
| R60 | Модули: ответственность/IO/errors/ready | MODULE_CONTRACTS §§2–12 | Архитектура | Каждая область имеет контракт/test IDs |
| R61 | Подробный план передачи Codex | Пакеты с файлами/gates/tests | Архитектура | IMPLEMENTATION_PLAN |
| R62 | Подтверждения и открытые риски | Evidence levels + E experiments | Архитектура | RISKS/RESEARCH |
| R63 | Самостоятельный аудит/трассируемость | Этот документ §§6–7 | Архитектура | Finding→correction table |
| R64 | Только документация, без реализации | Только10 Markdown outputs | Текущая работа | Нет исходников/установок/экспериментов |
| R65 | Все10 документов и перекрёстные ссылки | README index | Текущая работа | Файлы существуют/согласованы |
| R66 | Не выдумывать механику/не требовать сейчас | Virtual profile + Q-H future gate | Архитектура | Явный simulation_only и stage questions |

## 7. Самостоятельный архитектурный аудит

Аудит выполнен отдельным проходом по требованиям после составления спецификации. Это self-review, не аудит независимой внешней командой и не запуск тестов. Ниже реальные найденные проектные противоречия/опасные упрощения и принятые исправления.

| Finding | Последствие без исправления | Исправление в окончательной спецификации |
|---|---|---|
| SVG/font названия выглядят как обещание UA coverage | MVP мог бы пропускать ґ/ї и молча перейти на print | Exact coverage, missing-glyph failure, I-03 data gate |
| План соединения VHS можно принять за реализованный код | Форк основывался бы на отсутствующей функции | RESEARCH разделяет draft R2 и assembler implementation |
| У picture glyph отсутствует порядок | Ложное заявление о восстановлении истории | Provenance/alternatives, отдельные geometry/order metrics |
| Marks и cursive chain конфликтуют по stroke order | Точки теряются либо лишние pen lifts | Single-body/deferred-marks режим только с author approval |
| Variation после wrap выводит ink за поля | Невалидные последние буквы | Variation до measure; после placement только bounded line translation |
| Ligature пересекает emergency line break | Пропуск/дублирование графем | Reshape prefixes/suffixes с исходными IDs и boundary contexts |
| Контроллер неизвестен, но G-code нужен в MVP | Выдуманные Z/servo/GRBL assumptions | Explicit virtual target, отдельный I-H release |
| `ok` ошибочно равен completed | Подъём/смена страницы до окончания | Accepted/executed разделены; drain/idle/checkpoint |
| Независимая noise генерация зависит от вызовов | Перенос меняет буквы | Hash-based parameter choices и pinned versions |
| Dynamic planning хочется выполнить на host | Ненадёжный Python real-time control | Host bounds/feeds; firmware dynamics capability gate |
| Kraken stable конфликтует со skimage0.26 | Единое окружение могло не установиться | Раздельные local workers/envs, main и stable не смешиваются |
| InkSight card и code требуют разные TF | Ложный pinned recipe | Compatibility experiment до integration, не обязательная зависимость |
| G-code precision уничтожает короткие marks | Ї превращается в І | Post-quantization semantic validation; resolution failure |
| SVG preview может уйти на плоттер | Диагностические линии станут чернилами | Разные artifact roles/types и suffix |
| Bbox endpoints недостаточен для кривых | Выход дуги за границы | Экстремумы производных/conservative hull |
| «Без UI» противоречит ручной коррекции | Попытка построить GUI сейчас | Correction API/typed request files; UI отдельный III пакет |

Покрытие областей пользователя: все21 функциональные области сведены в9 модульных групп и12 разделов contracts; нет циклической зависимости layout↔shaping (WordShaper port в domain). Standard/personal сходятся на StylePack, все exports на PenPlan, hardware отделён после registration. Изолированная разработка возможна на own test fixtures и virtual target; окончательная визуальная приёмка без настоящего стиля невозможна и явно выделена.

Остаточные ограничения аудита: совместимость окружений не проверялась установкой; математические tolerance statements не проверялись программой; читабельность и физика не измерялись. Поэтому документ готов как инженерная спецификация, но метки software validated/hardware validated сейчас проекту не присваиваются.

Финальная документарная проверка: присутствуют все10 запрошенных Markdown-файлов; относительные междокументные ссылки ведут на существующие документы; все упоминания T-ID разрешаются в реестр74 сценариев; матрица содержит66 требований. Проверена форма commit SHA в ссылках и доступность выборки ключевых permalinks. Это проверка документации, а не исполнение описанных74 тестов. Вне `sources/` создана только документация; исходники реализации отсутствуют.
