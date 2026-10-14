# Модели данных и форматы

Нормативная спецификация v1.0. Типы ниже декларативны; это не исходный код. Алгоритмы: [ARCHITECTURE.md](ARCHITECTURE.md). Интерфейсы и ошибки: [MODULE_CONTRACTS.md](MODULE_CONTRACTS.md).

## 1. Общие правила

- UTF-8 без BOM при записи; reader разрешает один BOM входного TXT. JSON — конечные числа, без NaN/Infinity, комментариев, дублирующихся ключей и неявных преобразований строк в числа. Boolean не принимается как число. Пути только внутри выбранного пакета/рабочего каталога, без `..` и выхода через symlink.
- Оболочка каждого сохраняемого объекта: `format` (строка из реестра), `schema_version` (`major.minor`), `id`, `payload`. Метаданные времени и автора хранятся в `provenance`, отдельно от canonical payload hash.
- Unknown major → ошибка. Unknown minor/поля → ошибка, кроме объекта `extensions`, где ключи namespaced. Миграция явная, в новый файл; исходник неизменен. IDs уникальны в документе; семантические ссылки должны разрешаться.
- DTO неизменяемы после создания; списки не передаются как разделяемое изменяемое состояние. Реализация использует strict Pydantic на публичных границах, frozen dataclasses для внутренних небольших геометрических объектов. Одни и те же инварианты проверяются при загрузке и публикации.
- В геометрии float64. JSON сохраняет float round-trip значения, сортированные ключи и фиксированный порядок массивов. Внутренние значения не округляются до точности G-code. Для export decimal применяется явно указанный quantum, round-half-even, десятичная точка, запрет scientific notation, нормализация отрицательного нуля.
- Воспроизводимость byte-for-byte гарантируется для одинаковых canonical inputs, engine/algorithm version, dependency lock и export settings. Между платформами/версиями — геометрический tolerance contract, не обещание равных последних битов.

## 2. Координаты и размерности

| Пространство | Единицы, оси, начало | Допустимый переход |
|---|---|---|
| CaptureFrame | px или device_unit; явный y_direction; время отдельно | К GlyphFrame по baseline/x-height calibration; к RectifiedImage по homography |
| GlyphFrame | `gu`, x вправо, y вверх, baseline y=0, x-height=1000 gu | Uniform scale + bounded shear/translation → WordFrame |
| WordFrame | mm, x вправо, y вниз, baseline y=0 | Translation → PageFrame; затем разрешённая line translation |
| PageFrame | mm, x вправо, y вниз, верхний левый угол листа | Явный Affine2 → WorkFrame |
| WorkFrame | mm, Cartesian плоскость в осях backend | Kinematics/backend mapping → controller axes |
| Machine axes | Именованные оси, mm либо отдельно объявленные angular units | Только hardware backend |

У каждой геометрической коллекции `frame_id` и `units`; смешанные frames внутри неё запрещены. Нельзя выводить mm из DPI файла, размера bitmap или диапазона координат без calibration. Давление нормированного stylus не является высотой Z или силой в ньютонах.

`Affine2`: шесть finite scalars `(a,b,c,d,tx,ty)`, mapping `x'=a*x+c*y+tx`, `y'=b*x+d*y+ty`; from_frame/to_frame; determinant !=0. Матрицы применяются к точкам в указанном порядке. Tangent преобразуется линейной частью и нормируется. Reflection разрешена только при смене осей в registration, не как вариация почерка.

Номинальный glyph→word: `x_mm = x_gu * h/1000`, `y_mm = -y_gu * h/1000`, где h — желаемая x-height. Наклон — shear относительно baseline до отражения Y; h не называется «размером шрифта в pt».

## 3. Геометрический IR

### 3.1 Примитивы

| Тип | Поля | Инварианты |
|---|---|---|
| Point2 | x, y | finite, frame задан коллекцией |
| Line | kind=line, p0, p1 | Ненулевая длина, кроме импортируемого кандидата до очистки |
| Quadratic | kind=quadratic, p0, c1, p1 | Все точки finite |
| Cubic | kind=cubic, p0, c1, c2, p1 | Все точки finite |
| Bounds | min_x,min_y,max_x,max_y | min≤max; считается из пути, не доверяется файлу |
| Stroke | id, segments[1..N], source_refs[], role, direction_provenance | Сегменты направлены; соседние endpoint совпадают по правилам ниже |

Арки, рациональные кривые и filled polygons не входят в v1. Importer сообщает UNSUPPORTED_PATH_COMMAND для A; Q сохраняется. Z разрешён только как явно подтверждённое замыкание центральной линии и нормализуется в Line при ненулевом замыкании. Запрет контурных шрифтов нельзя обеспечить одним запретом Z: незамкнутый outline тоже может быть outline.

Непрерывность сегментов в опубликованном Stroke **точная**: общий endpoint хранится одним числовым значением. Importer вправе snap при расхождении ≤0.001 gu, логируя изменение; иначе разделить только с ручным подтверждением или отклонить. После математических операций общие endpoints вычисляются один раз. Самопересечение внутри буквы допустимо; оно не меняет stroke order.

Polyline — представление Stroke как последовательности Line, не отдельная семантика. Пустой stroke запрещён. Нулевая кривая не становится точкой автоматически. Для точек букв/пунктуации в MVP используются короткие авторские ненулевые штрихи, включённые в стиль и визуально принятые; контактная точка с dwell потребует нового explicit primitive/capability. Не удалять короткий штрих только по длине.

`role`: body / mark / connector / punctuation / diagnostic. Diagnostic геометрия никогда не попадает в production PenPlan. `direction_provenance`: captured / authored / inferred / unknown. Наличие direction не означает captured timing.

### 3.2 GlyphVariant

Обязательные поля: `variant_id`, `key` (NFC последовательность графем), `strokes` (список в авторском порядке), `advance_gu>0`, `context_tags`, `join_spec`, `provenance`, `review_status`, `critical_features`.

`context_tags`: набор из isolated, initial, medial, final; default вариант обязательно допускает isolated. Лигатурный ключ максимум 8 графем, без whitespace. Для v1 стиль должен иметь отдельные glyphs всех обязательных символов, даже если есть лигатуры: это нужно для переноса длинного слова.

`join_spec`:

- `mode`: none или single_body_deferred_marks.
- Для `none` всё исполняется в исходном порядке и не соединяется с соседями. Подходит сложным прописным и неподготовленным imports.
- Для `single_body_deferred_marks` ровно один body stroke, `body_stroke_id`; остальные stroke IDs перечислены в `deferred_marks` с фиксированным порядком. Автор явно разрешает откладывание этих marks до конца connected run внутри слова.
- `entry`/`exit`: nullable EndpointAnchor. Anchor содержит stroke_id, endpoint=start/end, tangent (единичный ненулевой вектор), class_id, allowed_partner_classes, max_gap_gu, max_vertical_delta_gu, max_angle_deg.
- Entry = начало body; exit = конец body. Anchor в середине пути не поддерживается v1, поскольку потребовал бы trimming и новую семантику. Direction tangent задаёт движение **по пути**, включая tangent входа в следующий body.
- Опубликованный anchor tangent обязан совпадать с фактической производной
  первого/последнего segment с допуском 1°. Значение из metadata не может
  подменять геометрию пути.
- `no_join_before/after`, script boundary policy, контекстные ограничения. При отсутствии anchors соединение запрещено.

`critical_features`: refs на точки/надстрочные/различающие элементы (например две marks у ї), обязательные stroke IDs. Validator проверяет их существование и сохранность после преобразований; смысловую правильность подтверждает автор.

`provenance`: author_id?, source_asset_hash?, capture_session_id?, source_crop_id?, license_id, source_method (manual_vector/online_capture/offline_reconstruction), source_revision?, transforms[], reviewed_by?, review_record_id?. Unknown источник не скрывать за значением captured.

### 3.3 StylePack

`format=hp-style`, `schema_version=1.0`, style_id, revision (immutable), display_name, scripts, license_record, glyph_frame, metrics, coverage, glyph index, join_rules, variation_policy, file_hashes.

Metrics: x_height_gu=1000; ascender/descender envelope из всех variants; space_advance_gu (по умолчанию 900), line_gap recommendation, supported x_height_mm range (первоначальная цель 2.5…5.0 mm, до приёмки не подтверждённый диапазон). Все variants лежат в объявленном envelope, включая marks и возможные connectors.

`coverage` — точный список NFC keys, не диапазон «Cyrillic». Минимальный набор:

- UA: `АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ` и соответствующие строчные.
- RU: `АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ` и соответствующие строчные.
- EN: A…Z и a…z, цифры 0…9.
- ASCII пунктуация U+0021…U+002F, U+003A…U+0040, U+005B…U+0060, U+007B…U+007E; плюс `«»“”‘’ʼ–—…№°±×÷≤≥→₴€`.
- Space U+0020, NBSP U+00A0, tab/newline/form-feed — layout controls, не рисуемые glyphs. U+202F учитывается как narrow NBSP с 0.5 nominal space; не требует ink glyph.

Unicode union не дублирует одинаковые code points между UA/RU; латинские и кириллические двойники остаются разными keys. Для `й/ї/ё` после NFC используются precomposed glyphs. Прочие combining marks допускаются только при наличии точного grapheme key; произвольная композиция акцента не обещается.

`join_rules`: class pairs с allow/deny, исключения по keys/variant IDs, clearance envelope, лимиты. Deny имеет приоритет. В default `ua-school-v1`: scripts не соединяются друг с другом; цифры, апострофы и пунктуация не соединяются с буквами. Это разрывает connected run, но не обязательно lexical word.

Пакет на диске: manifest.json, glyphs/<safe-id>.json, licenses/<id>.txt, review/coverage.json, review/pairs.json, provenance.json. В JSON key хранится явно; имя файла не источник Unicode semantics. В MVP импортируется каталог, не исполняемый plugin и не произвольный zip.

## 4. Текст и генерация

`TextRequest`: original_text, locale_hint (uk/ru/en/mixed; не меняет буквы), style_ref с revision, page_spec, variation_spec, seed (unsigned 64-bit), engine_version. Ограничения MVP: 1 MiB UTF-8 text, 100 000 графем, 1000 страниц. Превышение — RESOURCE_LIMIT, не частичный успех.

`NormalizedDocument`: original_hash, normalized_text, graphemes[{id,nfc,normalized_span,original_spans}], tokens, source_map, diagnostics. Spans полуоткрытые, индексы Unicode scalar values, не байты/UTF-16; UI самостоятельно переводит offsets. Один normalized cluster может ссылаться на несколько исходных code points. CRLF/CR → LF с сохранённым mapping.

`Token`: token_id, kind=word/space/hard_break/page_break, grapheme_ids, break_policy. Текст слова может включать апостроф; joins через него запрещены. Кавычка/пунктуация прикрепляется к соседнему слову правилом breaks, но сохраняет свой span.

`ResolvedRun`: source grapheme interval, GlyphMatch[], missing[], style_revision. `GlyphMatch`: key, consumed grapheme_ids, candidate variant IDs, context, stable occurrence ID. Longest licensed eligible key; ties по key и variant_id сортировке, не порядку файловой системы.

`ShapedWord`: token/fragment ID, source interval, selected variants, strokes, execution_groups, advance_mm, ink_bounds_mm, boundary type, diagnostics. Все variation и connectors уже определены. `execution_group` — связная body chain с marks после неё либо несоединяемый glyph с фиксированным порядком. Источник connector — пара source spans, не произвольная буква.

`PageSpec`: width_mm=210, height_mm=297; margins_mm по 15; x_height_mm=3.5; line_pitch_mm=9; paragraph_gap_mm=4; pen_width_mm=0.35 (модель визуальной ширины, не измеренная ручка); alignment=left; long_token_policy=grapheme_break; hyphenation=off. Проверка: printable rectangle имеет положительную площадь; requested h внутри принятого диапазона style.

`VariationSpec`: realism in [0,1], default 0.35; algorithm_id=hash-variation-v1. Верхние пределы при realism=1: glyph x/y scale ±2% (один общий scale для сохранения пропорций); shear ±2°; glyph baseline offset ±0.08 mm; word space ±5%; line translation Y ±0.10 mm. Font manifest может только уменьшить лимит. Никакого per-point jitter. Наклоны и offsets учитываются до соединений; line Y резервируется до layout.

Детерминированное число: SHA-256 канонического массива `[algorithm_id, seed_decimal, style_revision_hash, occurrence_id, parameter_name, candidate_index]`; первые 8 bytes unsigned big-endian; u=k/2^64. Числовой параметр = bounded symmetric mapping u; choice variants — сортированный список и floor(u*N). Чтобы не повторять вариант подряд при N>1, последний variant исключается для того же key в текущем lexical word; выбор из оставшихся тем же правилом. Нет зависимости от Python hash(), системного времени или глобального RNG. При splitting occurrence ID базируется на исходных grapheme IDs, а не номере строки.

`PageDocument`: document_id, input/params/style/engine hashes, pages[], complete=true, diagnostics. `Page`: index (0-based), PageSpec, lines[], placed_strokes[], ink_bounds, source coverage map. `PlacedStroke`: stroke + page placement + source refs; exporter получает уже вычисленные PageFrame точки, без неразрешённых transform chains.

Пустой/whitespace-only input → EMPTY_DOCUMENT и ноль production артефактов. Explicit page break не создаёт завершающую пустую страницу; последовательные page breaks внутри текста могут создавать пустые страницы с предупреждением и без motion-файла. Это поведение версионировано.

## 5. PenPlan — логическая последовательность пера

`format=hp-pen-plan`, units=mm, frame=PageFrame, page_id, operations[], source_document_hash, validation_report_hash.

Operation — discriminated union:

| op | Данные | Смысл |
|---|---|---|
| EnsurePenUp | op_id | Требование поднятого пера до любого travel; не доказательство физического датчика |
| TravelTo | op_id, target, source_refs | XY переход при UP; первый старт машины ещё не известен |
| PenDown | op_id | Контакт в текущей точке |
| Draw | op_id, stroke_id, segments, source_refs | Непрерывное рисование от текущей точки при DOWN |
| PenUp | op_id | Завершение контакта |
| Checkpoint | op_id, scope=word/page | Только при UP, граница возможного восстановления |

Начало: EnsurePenUp. Каждая группа: TravelTo start → PenDown → Draw → PenUp. Draw непрерывной chain может включать connector и несколько букв; source ranges не теряются. Конец каждой страницы UP + Checkpoint(page). Между словами всегда UP, даже при совпадении координат. Между main chain и каждой отдельной mark тоже нужные transitions. Повторные EnsurePenUp допустимы, лишние PenDown/PenUp — ошибка state machine. В v1 переупорядочивание запрещено.

План не содержит servo PWM, Z-height, accelerations и времён, восстановленных из фото. Raw capture timing может храниться в provenance; реальные write speed назначаются MotionProfile.

## 6. Машина, регистрация и MotionPlan

`MachineProfile`: profile_id, revision, simulation_only, dialect_id/version, transport_kind, axis definitions, reachable_region, forbidden_regions, kinematics_kind, capabilities, pen_config, feed_limits, accuracy_budget, controller_identity_requirements. Ни одно физически необходимое unknown поле не получает guessed default для реальной машины.

`capabilities`: cartesian_linear_moves; firmware_motion_planner; synchronized_pen; status_query; feed_hold; abort; homing; position_report; arcs (MVP false). Каждая capability содержит evidence_ref для hardware profile.

`pen_config`: actuator_kind=z_axis/servo/digital/custom; typed parameters только для выбранного backend; up/down position or values; settle_up_s, settle_down_s; clearance_mm?; fail_safe_behavior=known/unknown с описанием. Все device-specific значения версионируются. Нет свободной строки G-code в style или текстовом input.

`Registration`: page_id, profile_revision_hash, page_to_work Affine2, work_coordinate_system_id, calibration_id, evidence, valid_for_session_id. Номинальное размещение — rigid transform + axis reflection, scale=1. Калиброванная affine compensation допускается только с explicit provenance и пределами; fit-to-bed со сжатием страницы не выполняется автоматически.

`MachineState`: connection_session_id, firmware_identity, homed?, work_origin_verified, axes_position?, pen_state=UP/DOWN/UNKNOWN, queue_state, alarm?, timestamp. Планирование первого travel из известной позиции обязательно для hardware job; отсутствие позиции делает job неподготовленным к отправке.

`MotionPlan`: profile/registration hashes, start_state assumptions, operations, bounds_all_moves, approximation_report, timing_estimate, end_state, simulation_only. Операции: SetPen(UP/DOWN), MoveLinear(target axes, feed_mm_s, mode=travel/draw/actuate), Dwell(seconds), Barrier, Checkpoint. Все пути, включая Z и park, валидируются. Сегменты прямолинейные, G2/G3 отключены.

SetPen — **типизированная macro-operation** с полями target_state, actuator_kind, expansion[], settle_s, synchronization_evidence_ref. Expansion формируется backend planner до validation и содержит только allowlisted низкоуровневые операции данного actuator. Для virtual Z это MoveLinear с mode=actuate и Dwell. Expansion не дублируется рядом в operations; все validators/экспорт/оценка времени раскрывают её ровно один раз. Nested SetPen запрещён. Logical pen state меняется только после завершения expansion; движение XY во время actuation/settling запрещено. Независимый decoder сравнивает раскрытый план и восстанавливает pen transitions по правилам диалекта.

Internal feed mm/s; dialect G94 F = 60 × mm/s. Per-axis max проверяется по проекции скорости на ось. Effective acceleration проверяется как capability/profile setting; host не обещает точную достижимую скорость в каждом углу. Pen barrier должен быть реализуем диалектом, иначе UNSYNCHRONIZED_PEN.

**Виртуальный профиль `virtual-cartesian-z-v1`**: исключительно simulation_only=true; XYZ ranges X[0,210], Y[0,297], Z[0,10] mm; Page→Work `(x, 297-y)`; initial state (0,0,5), pen up; down Z=0, up Z=5; draw 10, travel 30, Z 5 mm/s; settle up/down=0.10 s; nominal axis acceleration=100 mm/s² только для оценки симулятора; pen width=0.35 mm; no park; no forbidden regions. Эти числа не являются рекомендованными настройками реального станка.

Virtual dialect v1 поддерживает только G21, G90, G94, G1 с XYZ/F, G4 P в секундах. Все перемещения G1; G0, M3/M5, M2, servo и ручная смена страницы не предполагаются. Завершение — подъём, dwell, Barrier, EOF. Каждая страница отдельный файл; запуск следующей страницы — отдельное действие вне файла.

В virtual dialect каждый G1 задаёт F явно; Z actuation и XY move идут разными строками. SetPen UP раскрывается в G1 Z5 с feed5mm/s и G4 P0.10, DOWN — в G1 Z0 с тем же feed и dwell. Barrier означает в offline interpreter завершение всех предыдущих последовательных операций; отдельного G-code слова не имеет. В реальном backend такой implicit barrier разрешён только при подтверждённой controller synchronization semantics. Decoder считает draw допустимым только после Z=0 + settle, travel — Z=5 + settle; промежуточные Z не являются состоянием готового пера.

## 7. Бюджет геометрии и сериализация команд

Номинальные программные требования для virtual profile: total deviation ≤0.05 mm; flattening ≤0.02 mm; quantization step q=0.001 mm (XY bound sqrt(2)*q/2); curve-bound calculation reserve ≤0.002 mm. Оставшийся запас не превращается в обещание физической точности. Registration residual/backlash/pen width измеряются отдельно.

Flattening после Page→Work transformation; в общем affine случае tolerance применяется в выходном пространстве. Conservative subdivision: расстояние всех control points до **конечного chord segment** ≤epsilon и chord length≤1 mm. Split De Casteljau при t=0.5; degenerate chord с удалёнными controls обязан делиться. Maximum depth=24, total segments/job≤2 000 000; достижение лимита → GEOMETRY_BUDGET_EXCEEDED, не выдача плохой аппроксимации.

После quantization снова проверить bounds и state continuity; сегмент, схлопнувшийся в ноль, можно убрать только если это не весь semantic stroke и не critical feature. В противном случае RESOLUTION_INSUFFICIENT. Не упрощать уже сплющенную кривую дополнительным непроверенным фильтром.

`CommandArtifact`: dialect/profile identity, media_type, ASCII bytes, page_id, SHA256, op_to_line_map, validation report, simulation_only. UTF-8 source text не интерполируется в исполняемые строки или comments. Неизвестный dialect запрещён. Команды повторно читаются независимым restricted parser и сравниваются с MotionPlan.

`SimulationReport`: completion_state, pen transition errors, text coverage errors, page/machine bounds errors, drawn_length_mm, travel_length_mm, pen_lifts, segment_count, lower_bound_time_s, conservative_time_estimate_s?, limitations[], input hashes. ETA не является фактическим временем оборудования.

## 8. Этап II: изображения, гипотезы, исправления

| Сущность | Основные поля и инварианты |
|---|---|
| SourceAsset | content_hash, original_filename, media_type, dimensions, capture_session, author, consent_ref, rights_record, stored_relative_path; оригинал immutable |
| ImageTransform | input/output hashes, EXIF orientation applied, homography?, deskew angle, pixel frame, scale_calibration?, parameters/version; inverse map сохраняется |
| Region | region_id, page_ref, polygon_px, baseline_polyline?, kind=line/word/character/ligature, parent_id, coordinate_frame; bbox не заменяет polygon |
| Transcription | region_id, predicted_text, corrected_text?, grapheme alignment?, model_id/revision, raw_scores, confidence_calibration_id?, status |
| ReconstructionCandidate | candidate_id, region_id, strokes/graph, proposed order, direction, provenance=inferred, geometry_score?, order_score?, alternatives[], unresolved_nodes[] |
| OnlineCapture | device/app/session IDs, frame, strokes in explicit order, points[x,y,t_ms?,pressure?], time_basis, pressure_semantics, calibration; timestamps nondecreasing within stroke |
| CorrectionEvent | event_id, target_id, parent_revision, operation, before_hash, after_hash, author_id, reason?, timestamp; append-only |
| StyleRevision | style_id, parent_revision?, accepted_variant_refs[], validation_report, review_decision, content_hash |
| DatasetSnapshot | immutable asset/revision lists, split assignments, rights manifest, preprocessing config, code/model versions |
| ModelRecord | backend, architecture, codec hash, weights hash, license, training_snapshot, parameters, validation metrics, environment lock, approval status |

Confidence — набор отдельных nullable оценок: text_confidence, segmentation_confidence, geometry_confidence, order_confidence; каждая имеет origin (heuristic/model/calibrated/human), scale и calibration_ref. Число 0.9 без калибровки не объявляется вероятностью правильного письма. Human-approved означает пригодность варианта, а не доказанность исторического порядка.

Жизненный цикл образца: imported → proposed → needs_review → approved либо rejected. Approved с изменением геометрии/метки порождает новую proposed revision. Только approved variants попадают в опубликованный production StylePack; сомнительные результаты не «доучивают» профиль сами себя.

Correction operations: set_transcript, adjust_polygon, split_region, merge_regions, assign_graphemes, split_stroke, join_strokes, reverse_stroke, set_order, adjust_control_points, set_anchor, mark_critical_feature, accept/reject. Каждый op обязан сохранить source refs; split/merge не требует соответствия «одна буква = один component».

## 9. Persistent storage и журнал задания

### 9.1 Desktop project v1

Переносимый GUI-документ имеет `format=hp-desktop-project` и
`schema_version=1.1`. Корень содержит `project_id`, пользовательское `name`,
`page`, ordered `objects[]`, `display` и необязательный `generation_cache`.
Версия 1.0 читается и мигрирует в памяти в 1.1; неизвестная версия или лишнее
поле — ошибка.

`page`: width/height mm, четыре margin mm, paragraph_gap_mm и pen_width_mm.
`TextObject`: object_id, name, Unicode text, visible, x_mm/y_mm, x_height_mm,
line_pitch_mm, pinned style_id/style_revision, seed и realism. `display` v1
содержит show_travel/show_markers. Object IDs уникальны; абсолютные пути и
QSettings layout в JSON не встраиваются.

Файл кодируется canonical UTF-8 JSON с LF и записывается temp + fsync + atomic
replace в том же каталоге. `generation_cache` хранит base64 артефакты
`GenerationResult`, их SHA-256, source SHA-256, document_id, page_count и
test_only_style. Cache восстанавливается только при совпадении source hash,
хешей всех артефактов и report metadata; иначе он отбрасывается без потери
исходного проекта. Cache относится только к текущей document revision и не
становится authority проекта.

Этап I: папка проекта с input.txt, request.json, pinned style manifest, page-0001.plan.json, page-0001.svg, page-0001.preview.svg, page-0001.gcode (если запрошен), report.json, job-manifest.json. Пользователь выбирает output directory; запись temp + atomic replace только новых артефактов, overwrite требует явного параметра. Не класть сюда чужие synced sources.

Canonical hash исключает created_at и путь output. Semantic IDs детерминированы по source spans/индексам; audit event IDs могут быть случайными и не влияют на render hash.

Этап II: `assets/<sha256>.<extension>` и SQLite catalog. Таблицы: assets, regions, transcriptions, reconstruction_candidates, correction_events, style_revisions, variant_refs, dataset_snapshots, model_records, jobs. FK включены, один writer, транзакция на correction/revision publish, row revision для optimistic concurrency. Миграции через user_version, до изменения backup; файлы сначала атомарно сохраняются, затем каталог ссылается на них. Непривязанные blobs удаляются только явной сборкой мусора.

Job journal I-H хранит planned_op, last_sent_line, last_accepted_line, last_confirmed_checkpoint, profile/registration/session hashes. Не хранить last_accepted как executed. После reconnect статус требует сверки; предыдущая registration автоматически недействительна, если потеряна позиция или сдвинут лист.

## 10. Вспомогательные типы публичных контрактов

| Тип / семейство | Обязательные данные |
|---|---|
| StrokeSet / PolylineSet | id, frame_id, units, ordered strokes, source_refs; PolylineSet допускает только Line |
| StyleSnapshot | style manifest, immutable variants by key, resolved file hashes, revision hash; filesystem paths не нужны shaper |
| StyleDraft | proposed manifest/variants, missing metadata, review tasks; production eligibility=false до publish |
| StyleSummary | style_id, revision, display_name, scripts, coverage counts, approved flag |
| CoverageReport | input/style hashes, supported/missing keys и spans, required vs present coverage, passed |
| PairCoverageReport | corpus hash, anchor classes, tested pairs, accepted joins/rejections/reasons, reviewer refs |
| GenerationContext | seed, engine_version, algorithm IDs, effective variation policy, resource budget, cancellation token; token не сериализуется |
| ImportPolicy | allowed format version/subset, limits, source license/provenance, explicit unit conversion, author_review_required=true |
| Calibration | source/target frames, baseline и x-height landmarks либо page correspondences, transform, residual?, method, evidence, revision |
| ApproximationReport | source/target hashes, target frame, epsilon, quantum, maximum certified error, segment count, budget status |
| TimingEstimate | lower_bound_s, conservative_estimate_s?, model_id, assumed acceleration/feed limits, unavailable reasons |
| SvgOptions | pen_width_mm, ink_color (RGB hex), numeric precision, include_metadata; style и glyphs не выбираются на этом этапе |
| DiagnosticOptions | show_travel, show_order, show_direction, show_margins; labels не production paths |
| Artifact / SvgArtifact / PreviewArtifact | role, media_type, deterministic filename, bytes/hash, source hashes; Svg=production, Preview=diagnostic |
| ArtifactBundle | job_id, artifacts[], immutable input references, reports[], completed flag; saved manifest создаётся последним |
| GenerationResult | PageDocument, ordered PenPlans, coverage/validation reports, effective request |
| DialectCapabilities | dialect_id/version, allowed codes/words, units/modes, pen mappings, synchronization rules, parser_version |
| DecodedCommandPlan | expanded operations, reconstructed modal states, line→operation map, dialect/profile hashes |
| PreflightReport | profile/registration/state/artifact hashes, checks, blockers, prepared_at; срок валидности связан с session, не только временем |
| PreparedJob | validated artifact hash, PreflightReport, session_id, registration_revision, allowed_start_state, status; не переносится между sessions |
| CandidateSet / RegionProposals | source refs, ordered candidate/region IDs, uncertainty, review tasks, backend/model/config hashes |
| EvaluationReport | dataset/split/model hashes, metric definitions, aggregate и per-group metrics, resource measurements, gate results |
| TrainSpec | backend/version, snapshot hash, charset, preprocessing config, seeds, hyperparameters, validation/early-stop policy, compute budget |

`ResourceBudget` задаёт input/page/variant/segment/shape-operation limits из этой спецификации и deadline; backend-specific memory/timeout добавляются для workers. Report-family использует общий ValidationReport/Diagnostic shape из MODULE_CONTRACTS. `GeometrySimulationReport` не имеет hardware ETA; полная SimulationReport включает соответствующие доступные уровни.
