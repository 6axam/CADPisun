# Публичные контракты модулей

v1.0. Здесь указаны декларативные сигнатуры, не исполняемый код. Все имена типов определяются [DATA_MODELS.md](DATA_MODELS.md); алгоритмы — [ARCHITECTURE.md](ARCHITECTURE.md). Имена будущих файлов в этом документе относятся к будущему репозиторию реализации, а не к созданным исходникам.

## 1. Общая семантика

`Outcome<T>` = success(value:T, diagnostics[]) или failure(errors[], diagnostics[]). Failure не содержит пригодный к отправке артефакт. Diagnostic: code, severity=info/warning/error, stage, message, source_spans[], object_ids[], details. Сообщение человеку не заменяет машинный code. Recoverable варианты — явно указанные здесь fallback, не blanket catch-and-continue.

Отмена — `CANCELLED`, до публикации manifest. Unexpected exception — INTERNAL_ERROR с correlation_id в логе, без молчаливого завершения и без частичного job. Публичные методы не меняют аргументы. Pure modules не пишут файлы, не скачивают модели, не открывают порты. ValidationReport: input hashes, validator version, checks[], errors[], warnings[], passed boolean; report действителен только для этих hashes.

Все операции имеют resource budget и cancellation token. Синхронные API ядра достаточны; будущий UI выполняет их в своём worker, без передачи event-loop objects в geometry. Progress: этап, processed/total? и job_id; частота ограничена orchestration, progress не меняет deterministic output.

## 2. domain / geometry

Будущие файлы: `domain/{models,errors,ports}.py`, `geometry/{curves,transforms,bounds,flatten,collision}.py`.

| Операция | Вход → выход | Предусловия/постусловия |
|---|---|---|
| validate_model | serialized envelope → Outcome<DomainModel> | Версия/числа/ссылки проверены, unknown fields не игнорируются |
| transform_strokes | StrokeSet, Affine2 → StrokeSet | from_frame совпадает; общий endpoint сохраняется; все anchors тем же transform |
| curve_bounds | Primitive → Bounds | Содержит всю кривую; не только endpoints |
| ink_bounds | StrokeSet, pen_width, reserve → Bounds | Все marks и connectors включены |
| flatten | StrokeSet, target_frame, tolerance, limits → Outcome<PolylineSet + ApproximationReport> | Порядок и направление сохраняются; лимит превышен → отказ |
| check_clearance | Shapes, allowed_contacts, tolerance → CollisionReport | Допустимые contacts — explicit ID pairs/regions, не глобальный флаг |
| validate_strokes | StrokeSet → ValidationReport | Конечность, непрерывность, critical features, отсутствие пустых paths |

Зависимости: domain — stdlib/Pydantic; geometry — domain/stdlib math. Готовые решения: стандартные численные операции, optional svg.path только на import boundary. Нельзя перенести в geometry зависимость от OpenCV или CNC dialect.

Ошибки: INVALID_NUMBER, FRAME_MISMATCH, INVALID_TRANSFORM, DISCONTINUOUS_STROKE, EMPTY_STROKE, GEOMETRY_BUDGET_EXCEEDED. Не удалять semantic marks в попытке починить geometry. Готовность: аналитические bounds, loops/degeneracies, rigid round-trip, conservative flatten и property tests T-G01…T-G06.

## 3. text

Файлы: `text/{normalize,segment,breaks,coverage}.py`.

| Операция | Контракт |
|---|---|
| normalize | TextRequest.original_text → Outcome<NormalizedDocument>; NFC, graphemes, spans, controls policy |
| find_breaks | NormalizedDocument, BreakPolicy → token sequence с explicit break/no-break boundaries |
| check_coverage | NormalizedDocument, StyleSnapshot → CoverageReport: missing keys со всеми позициями, coverage by script |

Зависимости: stdlib unicodedata, regex, domain. Snapshot не требует runtime storage reads. Coverage report проверяет фактический eligible glyph, а не только наличие key в manifest.

Ошибка MISSING_GLYPH перечисляет code points, видимый cluster, исходный offset и предлагаемый путь добавления образца. Не заменяет его на пустую строку/квадрат в production. UNSUPPORTED_CONTROL, UNSUPPORTED_SCRIPT_DIRECTION, INVALID_UTF8, EMPTY_DOCUMENT, NONBREAKABLE_OVERFLOW (последняя формируется layout).

Готовность: T-U01…T-U06; NFC/decomposed ї/й/ё идентичны после нормализации, source map корректен; Latin/Cyrillic lookalikes различаются. Unicode acceptance не означает coverage всего Unicode.

## 4. styles и import adapters

Файлы: `styles/{repository,validation,coverage,revision}.py`, `adapters/importers/{svg_paths,svg_font,tracer_json}.py` (tracer importer II-A; SVG пути I).

| Операция | Контракт |
|---|---|
| list_styles | StyleRepository → список StyleSummary без загрузки всех stroke arrays |
| load_style | style_id, revision → Outcome<StyleSnapshot> с проверенными hashes и полным immutable словарём |
| validate_style | StylePack → ValidationReport + CoverageReport + PairCoverageReport |
| import_centerline_svg | bytes, explicit metadata, ImportPolicy → Outcome<StyleDraft> |
| import_capture (II-A) | raw bytes, format_id, Calibration → Outcome<OnlineCapture> |
| publish_style | approved StyleDraft, expected_parent_revision → Outcome<StyleRevision> |

SVG import v1: только `svg/g/path` с numeric width/viewBox и path commands M/L/H/V/Q/T/C/S/Z; supported transforms translate/scale/rotate/matrix через нормализацию, shear только явная matrix. CSS, use/symbol, text, images, masks, clipPath, filters, external refs отвергаются. Каждый M начинает stroke; subpath order сохраняется. A не принимается до отдельного адаптера. Запрещены DTD/entity expansion; authoring exports с DOCTYPE предварительно нормализуются контролируемым редактором, не исполняющим внешние ресурсы. `fill=none` обязателен, но недостаточен для centerline eligibility — требуется author review.

SVG font importer читает glyph key/advance и вручную заданные baseline/x-height; поддержка multi-character key не означает automatic ligature correctness. Отсутствующие anchors → join none. Самостоятельно не изобретать entry/exit по bbox. Максимум SVG input 20 MiB, XML depth 64, 100 000 paths, 2 000 000 path coordinates; стиль целиком ≤100 MiB и ≤100 000 variants. превышение → RESOURCE_LIMIT.

Запись publish — единственная mutation этого модуля: temp directory → проверка всех refs → атомарное размещение новой revision → обновление latest pointer. Concurrent parent mismatch → REVISION_CONFLICT, без перезаписи.

Готовые средства: defusedxml, svg.path; альтернативы и licenses в TECH_STACK. Ошибки: STYLE_NOT_FOUND, HASH_MISMATCH, LICENSE_RECORD_MISSING, INVALID_ANCHOR, UNSUPPORTED_SVG_FEATURE, UNREVIEWED_SAMPLE, REVISION_CONFLICT. Готовность: T-S01…T-S05. Release не проходит без файла реального `ua-school-v1` и отчёта визуальной приёмки.

## 5. shaping: resolution, variants, joins

Файлы: `shaping/{resolve,variants,placement,joins,schedule}.py`.

`WordShaper.shape(source_fragment, boundary_context, StyleSnapshot, GenerationContext) → Outcome<ShapedWord>`.

GenerationContext: engine/algorithm IDs, seed, pinned variation config, original grapheme IDs, local budgets. Boundary context явно указывает forced fragment start/end; ни номер страницы, ни системный RNG не используются. Для NBSP group application/layout вызывает shape отдельных words, между ними обязательный lift.

Внутренние логические контракты:

- resolve возвращает consumed grapheme ranges и eligible variants; ranges точно покрывают fragment без overlap.
- vary преобразует whole variant + anchors и записывает effective parameters; не меняет source strokes.
- connect возвращает accepted connector или RejectedJoin(reason), а не исключение на любую неподходящую пару.
- connect требует взаимного разрешения anchor classes с обеих сторон и
  исполняет `no_join_after`/`no_join_before` до построения кривой.
- schedule выдаёт executable groups с body chain/deferred marks, покрывающие каждый обязательный stroke один раз.

Зависимости: domain/geometry, не storage/layout/export. Готового cursive движка не используется по RESEARCH. Перестановка/разворот исходных strokes допускаются только как явная correction stage II, не shaping optimization.

Постусловия: source coverage 100%; конкретные selected variants известны; ink bounds включают variation/marks/joins; shape повторяем для одинакового запроса; при split лигатуры контекст обновлён, графемы не теряются. Join rejection — warning/info; invalid data либо неустранимая коллизия — failure. Ошибки: NO_ELIGIBLE_VARIANT, INVALID_STYLE_PAIR, INVALID_JOIN_GEOMETRY, RESOURCE_LIMIT. Готовность T-J01…T-J07, T-R01…T-R03.

## 6. layout

Файлы `layout/{lines,pages}.py`.

`layout(NormalizedDocument, StyleSnapshot, PageSpec, GenerationContext, WordShaper) → Outcome<PageDocument>`.

Использует порт WordShaper для regular words и reshape oversized fragments. Политика greedy, source mapping и measured envelopes описаны в ARCHITECTURE §7. Внутри нет чтения файлов и явных вызовов G-code. Полный PageDocument возвращается до side effects; для текущих лимитов streaming output не требуется.

Постусловия: все glyph ink envelopes внутри printable rectangle; ordered lines; нет пропусков/дублирования source ranges; одинаковые inputs дают одинаковые breaks. Hard break/NBSP/glued punctuation соблюдены. Если requested line pitch мал, effective pitch увеличен по формуле с warning; user-visible размер букв не меняется.

Ошибки: INVALID_PAGE_SPEC, GLYPH_TOO_WIDE, LINE_TOO_TALL, NONBREAKABLE_OVERFLOW, PAGE_LIMIT, RESOURCE_LIMIT. Не clip, не truncate, не shrink-to-fit. Готовность T-L01…T-L07, включая длинные tokens и negative bearings.

## 7. strokes и SVG

Файлы `strokes/{compile,validate,simulate}.py`, `adapters/svg/{writer,preview}.py`.

| Операция | Контракт |
|---|---|
| compile_pen_plan | Page → Outcome<PenPlan> |
| validate_pen_plan | PenPlan, PageSpec → ValidationReport |
| simulate_pen_plan | PenPlan → GeometrySimulationReport без аппаратной ETA |
| export_svg | validated Page/PenPlan, SvgOptions → Outcome<SvgArtifact> |
| export_preview | validated PenPlan, DiagnosticOptions → PreviewArtifact |

SvgOptions только внешний вид разрешённого single-color stroke; width должен совпадать с использованным для bounds. Изменение width требует повторной проверки. PreviewArtifact имеет role=diagnostic, и тип не принимается motion/export-gcode APIs.

Постусловия PenPlan: начальный UP request, travel только UP, draw только DOWN, endpoints непрерывны, все marks ровно один раз, слово/страница завершаются UP. SVG получает geometry из того же плана; display labels формируются отдельным preview writer. Экспорт pure bytes; сохранение делает application/storage.

Ошибки PEN_STATE_VIOLATION, PATH_DISCONTINUITY, PAGE_BOUNDS, SOURCE_COVERAGE_MISMATCH, DIAGNOSTIC_ARTIFACT. Готовые средства: XML writer stdlib; browser/существующий SVG viewer вне package. Готовность T-P01…T-P04, T-E01…T-E03.

## 8. motion и machine profiles

Файлы `motion/{profiles,registration,preflight,planning,limits,timing}.py`.

| Операция | Контракт |
|---|---|
| validate_profile | MachineProfile → Outcome<ValidatedProfile> |
| preflight | PenPlan, ValidatedProfile, Registration, MachineState → PreflightReport |
| plan_motion | те же inputs + MotionOptions → Outcome<MotionPlan> |
| validate_motion | MotionPlan, profile, registration → ValidationReport |
| estimate_time | MotionPlan, documented timing model → TimingEstimate |

Без реального state разрешён только simulation_only профиль с явным synthetic start state. Для hardware отправки profile identity/capabilities подтверждаются connect handshake; artifact с несовпадающим profile hash не принимается.

Готовые решения: firmware-native dynamic planner; geometry core. Host выбирает feeds не выше requested и per-axis projection caps, фиксирует Z actuation/settle, проверяет work envelope и forbidden regions, аппроксимирует после transform. Без mapped units, synchronized pen и firmware planner I-H профиль не считается реализованным.

TimingEstimate содержит lower bound Σlength/feed + обязательные dwells; virtual conservative estimate может суммировать stop-to-stop trapezoids по сегментам с заданным acceleration, что обычно переоценивает firmware blending. Для настоящего устройства без подтверждённой timing model detailed ETA=null, limitations обязательны.

Ошибки PROFILE_INCOMPLETE, PROFILE_MISMATCH, REGISTRATION_INVALID, UNKNOWN_START_STATE, UNREACHABLE_PATH, FEED_LIMIT, RESOLUTION_INSUFFICIENT, UNSUPPORTED_KINEMATICS, UNSYNCHRONIZED_PEN. Готовность T-M01…T-M07, сначала virtual.

## 9. G-code dialect adapters

Файлы `adapters/gcode/{base,virtual_xyz,parser}.py`; реальный dialect позже отдельным файлом.

`Dialect.describe() → DialectCapabilities`.

`Dialect.emit(validated MotionPlan, ValidatedProfile) → Outcome<CommandArtifact>`.

`RestrictedDecoder.decode(CommandArtifact, profile) → Outcome<DecodedCommandPlan>`.

`compare_plans(MotionPlan, DecodedCommandPlan, AccuracyBudget) → ValidationReport`.

RestrictedDecoder написан по спецификации grammar **независимо от emitter helpers**, иначе round-trip может повторить одну и ту же ошибку. Он понимает только emitted subset конкретного dialect, modal units/feed/absolute state, pen mapping. Unknown word/code → error, не skip. Переход в G91/G20 или включение постороннего actuator через вставленный текст запрещено.

Постусловия: ASCII, decimal units, round-tripped path и pen sequence в допусках; без произвольных raw command strings; per-page artifact, финальное UP. Для virtual только grammar из DATA_MODELS §6. Реальный exporter не называется GRBL до проверки его конкретного subset и устройства.

Ошибки UNSUPPORTED_DIALECT, UNSUPPORTED_COMMAND, MODAL_STATE_ERROR, COMMAND_ROUNDTRIP_MISMATCH, UNSAFE_PROFILE. Готовность T-E04…T-E07. Известный valid virtual файл подтверждает только соответствие нашему virtual dialect, не universal controller support.

## 10. Transport / sender I-H

Файлы `adapters/transport/{base,fake,serial}.py`, `machine/{session,protocol,journal}.py`.

Transport port: open(connection_config) → connection; write(bytes) → bytes_written; read(max_bytes,deadline) → bytes/status; close(). Transport не знает букв и PenPlan. Передача частичного buffer обрабатывается sender; write() не означает принятие контроллером.

Protocol port: identify → ControllerIdentity; query_state → MachineState; send_line → accepted/error; hold → request handle; abort → request handle; wait_idle → acknowledged checkpoint. Только backend определяет, как эти операции отображаются в bytes.

`MachineSession.prepare(validated CommandArtifact, observed state) → PreparedJob` без движения.

`MachineSession.start(PreparedJob) → job_id + event stream`, `pause`, `resume`, `abort`, `status`. Start — единственная операция запуска, не вызывается render/export. PreparedJob invalidated после смены profile/registration/session.

Events: sent, accepted, status, checkpoint_confirmed, alarm, disconnect, completed. Journal persistent; completed только после финального drain/idle. Автоматического retry движения нет. FakeTransport в тестах выдаёт scripted byte fragments, delayed/reordered status lines и disconnect, не является эмуляцией реальной физики.

Зависимости pySerial extra; no sudo, no automatic firmware settings. Ошибки PORT_ACCESS, HANDSHAKE_TIMEOUT, FIRMWARE_MISMATCH, CONTROLLER_ERROR, ACK_TIMEOUT, POSITION_LOST, DISCONNECTED, RESUME_UNSAFE. Готовность — T-H01…T-H06 плюс физические H-A…H-D. Пока аппаратный gate не выполнен, start для virtual artifact всегда SIMULATION_ONLY.

## 11. Learning II: CV, HTR, segmentation и reconstruction

Файлы `learning/{ingest,preprocess,regions,recognition,reconstruction,corrections,datasets,training}.py`; тяжёлые backends в отдельных adapter packages/envs.

| Port | Вход → выход | Инварианты и отказ |
|---|---|---|
| ImagePreprocessor | SourceAsset + config + optional corners → ProcessedAsset + transforms | original immutable; неизвестный physical scale остаётся unknown; DEWARP_REQUIRED при кривизне |
| Segmenter | ProcessedAsset + model ref → RegionProposals | Frame и polygon, confidence/provenance; не обещает character cuts |
| Recognizer | masked line crop + pinned model → TranscriptionCandidate | Текст/сырые scores/codec, no silent autocorrect; MODEL_CODEC_MISSING |
| Aligner | line crop + corrected transcription + model → AlignmentProposals | Диапазоны confidence, ambiguity; не ground truth |
| Reconstructor | region/mask + optional alignment/style priors → CandidateSet | Сохраняет graph/alternatives; captured order не фабрикуется |
| CaptureImporter | online file + calibration → OnlineCapture | Настоящие timestamps отдельно от inferred; PRESSURE_UNCALIBRATED warning |
| CorrectionService | base revision + typed operations → NewRevision + events | Atomic transaction, optimistic concurrency; REVISION_CONFLICT |
| StyleBuilder | approved samples + policy → StyleDraft | Coverage/context/anchors/licensing checked; unreviewed исключены с report |
| DatasetBuilder | approved annotations + split policy → DatasetSnapshot | Нет одной страницы/сессии в разных splits; hashes и rights |
| Trainer | DatasetSnapshot + TrainSpec → ModelCandidate | Явный запуск, никакой автоматической production замены |
| Evaluator | ModelCandidate + frozen test snapshot → EvaluationReport | CER/WER/class metrics/latency, leaks check |
| ModelRegistry.promote | ModelCandidate + passed report + review → ModelRecord | Immutable weights hash, pinned environment, rollback previous |

Готовые backends: OpenCV/skimage для CV, Kraken для segmentation/HTR, InkSight только optional experiment. Imported photos не «обучают генератор» напрямую: сначала sample proposal → review → новая StylePack. Неизвестная буква может быть сохранена как unlabelled sample без её использования в тексте.

Worker boundary: job directory с versioned request.json, read-only content-addressed input refs, output temp directory, result.json/diagnostics.json; schema=hp-worker-job/1.0, operation enum, request_id, time/memory budgets. Process запускается allowlisted backend entrypoint без shell interpolation. Только локальные файлы, stdout для progress records, stderr для logs. Timeout убивает job и сохраняет исходники. Это локальная изоляция environments, не сетевой сервис.

MVP II-A не требует worker/torch. II-B normalizer и correction services остаются в основном package; CV/HTR результаты пересекают границу только как наши DTO/файлы. Job requests не содержат произвольный Python module name. Проверка модели/весов и отсутствие remote code execution — обязанность ModelRegistry.

Готовность: T-C01…T-C07 и T-D01…T-D05; каждый backend проходит один и тот же contract suite. Неуспех автоматизации оставляет доступным ручной workflow.

## 12. Application, storage и будущий UI API

Файлы `application/{service,jobs}.py`, `storage/{files,catalog}.py`, `cli.py`.

| Метод | Назначение |
|---|---|
| inspect_text | TextRequest → CoverageReport без генерации |
| generate | TextRequest → Outcome<GenerationResult: PageDocument, PenPlans, reports> |
| export | GenerationResult + requested formats/profile/registration → Outcome<ArtifactBundle> |
| simulate | validated PenPlan/MotionPlan/CommandArtifact → соответствующий Report |
| save_bundle | ArtifactBundle + target directory + overwrite policy → SavedManifest |
| list_styles / inspect_style | Read-only style summaries и coverage |
| cancel | job_id → cancellation request/result |
| propose_samples / apply_corrections / publish_style (II) | Версионированные операции без проектирования экрана |
| prepare_machine_job / start_machine_job (I-H) | Раздельные операции подготовки и явного запуска |

CLI возвращает exit 0 success, 2 invalid input/config/coverage, 3 geometry/style/layout, 4 resource limit (и device/protocol после появления I-H), 5 environment/IO, 130 cancelled. Предупреждения доступны в JSON report и stderr, не засоряют SVG/G-code stdout. Команды концептуально: inspect, generate, export, simulate, styles validate; machine prepare/send только I-H; samples/corrections/train только II. Никакого автоматического send после export.

Storage stores immutable inputs/revisions, atomic manifest, каталог II. FileStore не импортирует geometry/recognizer; принимает bytes/DTO serializer. Limits, disk-full, permissions, hash mismatch возвращаются явно. При ошибке temp files могут остаться для диагностики, но отсутствует completed manifest; следующий run не принимает их за готовое задание.

### 12.1 Raw capture boundary

Files `capture/{models,repository}.py` не импортируют Qt. `serialize_capture`
принимает validated `CaptureSession` и выдаёт canonical bytes.
`load_capture_bytes` применяет byte budget, strict JSON без BOM/duplicate keys и
принимает только `hp-capture/1.0`. `CaptureRepository.store` публикует raw bytes
атомарно по content SHA-256 без overwrite; повторная запись тех же bytes
идемпотентна, несовпадение existing bytes даёт `CAPTURE_HASH_MISMATCH`.
`load(hash)` повторно проверяет имя/hash до parsing. Ошибки unknown format/schema,
resource limits, event/time/ID order, coordinate frame и capability mismatch не
исправляются молча.

`CaptureQueueStore` читает/атомарно заменяет только editable
`hp-capture-queue/1.0` metadata. Queue navigation не переписывает raw captures;
skip и rejected hashes являются явными review decisions. Coverage dashboard
считает variants из `CaptureRepository` за вычетом rejected hashes и применяет
настраиваемый required_variants без продуктового auto-approval.

`DraftStore` атомарно хранит `hp-style-draft/1.0`; операции preferred,
accepted/rejected и delete создают следующую запись history, не меняя
`CaptureRepository`. GUI показывает только non-deleted variants, но audit и
восстановление сохраняют tombstones. Reopen всегда повторно загружает raw bytes
по capture_sha256.

### 12.2 Capture processing boundary

`capture/processing.py` не импортирует Qt. `process_sample(sample,
source_capture_sha256, parameters)` детерминированно возвращает
`ProcessedCapture` в том же logical-pixel frame. Он сохраняет one-to-one
порядок/IDs/boundaries strokes, captured direction и endpoints, не объединяет
и не разворачивает paths. Характерные corners и loop anchor защищаются от
smoothing/simplification. Point mark остаётся отдельным directed mark.

Перед возвратом pipeline измеряет symmetric source/result deviation с
ограниченным шагом и добавляет conservative sampling/curve-flattening margin.
Результат с upper bound выше declared tolerance отвергается; fallback может
уменьшить simplification вплоть до исходной polyline, но не ослабляет tolerance.
До выделения resampled arrays проверяется общий point budget.
`ProcessedRepository` canonical-сериализует `hp-processed-capture/1.0`,
публикует его atomic content-addressed write под source hash, а при load снова
проверяет derivative hash, существование/hash raw capture и source sample link.
UI отвечает только за выбор параметров
и Raw/Processed overlay; отмена overlay не вызывает удаление raw bytes.

### 12.3 Glyph metric normalization boundary

`capture/metrics.py` не импортирует Qt. `normalize_processed_glyph(processed,
processed_sha256, raw_sample, shared_profile, variant metadata/override)`
проверяет sample/frame identity и применяет один affine scale из shared
baseline/x-height guides ко всем control/end points. Он может менять только
horizontal origin/bearings, declared advance и явный baseline offset; per-glyph
vertical bbox scaling запрещён.

`MetricProfileStore` атомарно хранит contiguous editable profile revisions.
`NormalizedRepository` до store/load повторно проверяет raw SHA/sample,
processed SHA/source link, profile hash, analytical bounds, envelope и
bearings. `NormalizedGlyph.physical_preview_strokes()` выполняет явное gu→mm
преобразование с инверсией Y. GUI показывает отдельный GlyphFrame preview,
физические размеры и ручные controls; изменение параметров инвалидирует только
preview/normalized derivative, не raw или processed sources.

### 12.4 Manual annotation and pair preview boundary

`capture/annotation.py` не импортирует Qt. `validate_annotation(annotation,
normalized_glyph)` проверяет exact source/order/roles, one-body rule, original
deferred-mark order, critical refs и endpoint/tangent agreement. AnnotationStore
записывает только следующую contiguous revision после повторной проверки всей
raw→processed→normalized source chain.

`annotation_to_glyph_variant` создаёт draft existing `GlyphVariantFile`, не
меняя geometry и не повышая review status. `preview_join(left,right)` размещает
эти variants через существующий `place_glyph` и вызывает production join
decision `shaping.joins.connect`; UI показывает connector или точную reject/lift
reason. Ни preview, ни editor не исправляют несовместимый anchor автоматическим
reversal, reordering или новым connector metadata.

Готовность: end-to-end T-A01…T-A04; import core без optional deps, работа offline, отмена, atomic failure и JSON diagnostics. Будущий UI получает source spans и IDs для выбора букв, но никогда не исполняет неизвестные command fragments или SQL.

## 13. Desktop GUI

Файлы `gui/{application,main_window,document,backend,canvas,workers,theme}.py`.

| Компонент | Контракт |
|---|---|
| ProjectDocument | Versioned page/text/grid/style/display state, revision/dirty/undo; generated bytes не являются authority |
| DesktopApplicationAdapter | Immutable project snapshot → shared GenerationResult; использует application/layout/stroke/motion adapters |
| GenerationWorker | Snapshot revision + adapter → success/error signal; widgets не меняются из worker thread |
| PageCanvas | Backend SVG/PenPlan bytes + non-production object/grid overlays → scene in PageFrame mm; CAD selection, move, independent-axis grid snap, zoom/pan/fit |
| HandwritingCaptureWidget | Mouse/tablet/touch events → ordered `CaptureStroke`; fixed logical-pixel frame, monotonic elapsed time, nullable real pressure, synthesized-mouse suppression; no geometric processing |
| StatusTelemetry | PageCanvas paint events/cursor → measured FPS и PageFrame mm coordinates; application version → постоянная подпись; generation lifecycle → indeterminate/success/error progress |
| ProjectStore | `hp-desktop-project/1.0…1.3` ↔ canonical JSON; verified optional GenerationResult cache, atomic replace, unknown version error |

Старый worker result не применяется к новой revision. Одновременно выполняется
не больше одной generation job документа. Export копирует проверенные bytes из
последнего результата либо из проверенного cache текущей revision;
dirty/отсутствующий result требует Generate. Закрытие dirty project требует
решения пользователя. Qt layout сохраняется в QSettings отдельно от portable
project JSON.

`DesktopApplicationAdapter` принимает из `objects[]` только видимые
`TextObject`. `GridObject` не пересекает composition boundary: изменение его
геометрии, клетки, линии, цвета или видимости не делает уже рассчитанные
машинные артефакты семантически устаревшими. Привязка действует независимо по
X и Y в пределах 1.5 mm и никогда не изменяет координаты без движения объекта.
