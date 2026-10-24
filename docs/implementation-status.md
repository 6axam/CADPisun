# Состояние реализации

## PHOTO-06 — явная физическая калибровка, 2026-10-24

- `PhysicalScaleCalibration` хранит frame-bound X/Y `mm_per_px`, origin,
  method, optional uncertainty и reference pitch в новом immutable manifest.
  Pixel geometry не получает физический размер автоматически.
- Studio предлагает сохранение введённого размера и отдельный 5 mm preset
  только после измерения ruling geometry. Для ruled листа калибруется лишь Y;
  diagnostics честно показывает неизвестную X-ось. Изменение geometry очищает
  старую калибровку.
- Qt-free conversion проверена для cell/rule-relative и skewed metric axes;
  GUI tests проверяют preset, manual scale, persistence/reopen и invalidation.

## PHOTO-05 — геометрия клеток и линеек, 2026-10-24

- `photo-cv` измеряет periodic pixel geometry для ruled/squared листов:
  pitch, phase/origin, направления и residual из длинных Hough segments.
  Модель требует как минимум четыре повторяющиеся линии и отвергает sparse
  table borders вместо фиктивной геометрии.
- В Studio есть Detect spacing, magenta overlay измеренного frame, отображение
  residual и ручные поля pixel pitch/origin/angle. Сохранение создает human
  override в новом immutable manifest; physical mm не объявляются.
- Synthetic tests проверяют clean/skewed/occluded/crossing-ink pages, grid
  intersections, table negative, ручную persistence/reopen и GUI overlay.

## PHOTO-04 — классификация бумаги тетради, 2026-10-24

- `photo-cv` теперь локально классифицирует blank, squared, ruled, mixed или
  unknown по повторяющимся длинным линиям; результат содержит честную
  heuristic confidence, метод и frame ID.
- Workspace показывает proposal, confidence и ручной выбор. И proposal, и
  human override создают отдельный immutable manifest; при наличии rectified
  PNG анализируется его frame. Оригинальные bytes и geometry не меняются.
- Synthetic tests покрывают все классы, короткий handwriting поверх линейки,
  table/mark interference, invalid frame, save/reopen override и исправленный
  frame. Шаг, фаза, origin и физические миллиметры намеренно остаются пустыми
  до следующих задач.

## PHOTO-03 — исправление перспективы страницы, 2026-10-23

- Optional `photo-cv` фиксирует OpenCV headless 4.13.0.92. Base/CLI и обычный
  photo import не импортируют cv2 или NumPy.
- Автоматический contour/quad proposal остаётся проверяемой эвристикой; ручные
  четыре перетаскиваемых угла доступны как обязательный fallback. Отсутствие
  страницы и ограничение planar-only показываются явно.
- Embedded orientation, homography и optional fine deskew составляются в одну
  forward matrix; inverse проверяется. Aspect ratio выводится из сторон
  quadrilateral, а не из размеров GUI.
- Corrected PNG хранится по SHA-256. Новый immutable photo manifest добавляет
  frame, transform и page polygon, сохраняя точные байты исходника и старую
  revision.
- Synthetic tests проверяют auto/manual paths, no-page diagnostics, orientation,
  inverse-map error, persistence и повторное открытие corrected preview.

## PHOTO-02 — интерфейс импорта фото, 2026-10-23

- В Handwriting Studio добавлен отдельный workflow выбора и безопасного импорта
  PNG, JPEG, WebP, BMP и статического GIF, не связанный с холстом документа.
- Original и corrected preview отображаются рядом; доступны общий zoom, 1:1,
  fit, поворот правого preview на 90° и reset. Просмотровые операции не меняют
  immutable оригинал и не записываются как выполненная коррекция перспективы.
- Диагностика показывает реальный формат, размеры, encoded bytes, embedded
  orientation, исходный SHA-256, manifest и незапущенные этапы анализа.
  Последний проверенный импорт восстанавливается после повторного запуска.
- Headless Qt тесты проверяют точные сохранённые байты, сравнение, controls,
  ошибочный ввод, восстановление состояния, украинскую локализацию и изоляцию
  от capture workspace.

## GUI-10 — issue #9, 2026-10-23

- Properties получил вертикальную прокрутку; Output больше не перекрывает
  правый dock. Project, Editing и View стали отдельными адаптивными панелями,
  а Studio сохраняет читаемые области в узком окне.
- Preview показывает настоящий diagnostic SVG и virtual G-code. Execution
  проигрывает операции принятого PenPlan с виртуальной головкой и явно остаётся
  simulation-only без драйвера оборудования.
- `hp-desktop-project/1.5` добавляет проверенный embedded ArtworkObject для SVG,
  PNG, JPEG, WebP, BMP и GIF. Референс исключён из машинных артефактов; production
  SVG можно дополнительно экспортировать в PNG.
- Help → Controls показывает текущие клавиши и жесты. Program Settings сохраняет
  язык и переназначения клавиш и сбрасывает dock layout. About сообщает версию,
  формат проекта и статус оборудования. Сборка: `0.2.0+20261023.1`.

## GUI-09 — issue #7, 2026-10-16

- Верхний текстовый toolbar заменён двумя настоящими dock-панелями. Панель
  «Інструменти» использует квадратные символьные кнопки, располагается под
  «Об’єкти проєкту», переносится, плавает и переключается через «Вигляд».
- Верхняя панель «Режими» первоначально содержала рабочий режим «Об’єкт» и
  отключённые заготовки «Перегляд»/«Виконання»; они реализованы в GUI-10.
- Названия, подсказки и dock titles локализованы на английский и украинский;
  расположение и видимость новых панелей сохраняются в QMainWindow state.

## GUI-08 — завершён 2026-10-14

- В строке состояния постоянно отображаются версия приложения, измеряемый по
  paint events FPS и координаты курсора в миллиметрах A4.
- Информационные, успешные, предупреждающие и ошибочные операции имеют
  отдельные цвета и единый путь отображения.
- Фоновая генерация показывает indeterminate progress без выдуманного процента,
  затем подтверждённый success/error/stopped outcome. Проведена offscreen
  visual QA нижней строки и полного окна.

## GUI-07 — завершён 2026-10-14

- Исправлено безопасное переключение видимости с обновлением результата;
  добавлены английский/украинский интерфейс, CAD-выделение и групповое
  перемещение объектов.
- Текстовые поля независимы от авторитетной геометрии письма; свойства
  сгруппированы попарно и редактируют X/Y/ширину/высоту поля.
- `hp-desktop-project/1.3` добавляет `GridObject` с клеткой, тремя видами линий,
  цветом и независимой привязкой X/Y. Backend принимает только TextObject;
  тест сравнивает byte-identical generated artifacts с сеткой и без неё.

## GUI-08 — issue #5, 2026-10-16

- `hp-desktop-project/1.4` добавляет межсимвольный интервал, поворот,
  отображаемый диаметр и одну из 16 цветовых групп TextObject.
- Рабочее поле стало обязательной границей генерации: backend использует его
  для переноса строк, проверяет геометрию после поворота и сообщает overflow
  без вывода частично вышедших за рамку штрихов.
- Properties редактирует начало текста относительно рабочей области, показывает
  название рядом с текстом и предоставляет 16 цветовых групп. Выбранный цвет
  применяется к рамке, production SVG и diagnostic SVG.
- Выбранная область имеет восемь маркеров размера; боковые изменяют одну ось,
  угловые сохраняют пропорции. Наведение выделяет границу широким пунктиром,
  overflow отмечается красным кругом с белым крестом в центре области.

## GUI-06 — завершён 2026-10-13

- Добавлены стандартные shortcuts, dirty-close Save/Discard/Cancel, сохранение
  geometry/dock state и canvas diagnostics в QSettings. Fit-to-page теперь
  корректно пересчитывается при resize/dock layout, ручной zoom отключает
  автоматический fit.
- Исправлены найденные при визуальной проверке ошибки выбора StylePack и
  каталога validation. Реальное окно запущено через Wayland platform plugin;
  сохранены production/toolpath и diagnostic/validation screenshots.
- Wheel установлен в чистое CPython 3.12.12 окружение без PySide6: `hplot
  --help` и импорт CLI успешны, Qt отсутствует. GUI entrypoint отдельно прошёл
  Wayland startup smoke test.
- README, desktop guide, DATA_MODELS и screenshot provenance синхронизированы.
  Финальный накопленный набор: 102/102 tests.

## GUI-05 — завершён 2026-10-13

- File → Export сохраняет exact bytes принятого production SVG,
  diagnostic SVG, virtual G-code или validation report через системный диалог
  и атомарную замену файла.
- Export доступен только когда generation revision совпадает с текущей
  document revision; после любого изменения действия блокируются до новой
  генерации.
- Diagnostics показывает реальные style/profile/round-trip статусы, Toolpath —
  длины, pen lifts, segment count и нижнюю оценку виртуального времени. G-code
  в интерфейсе везде обозначен `simulation only`; sender отсутствует.
- Проверены все четыре экспорта, запрет внутренних artifacts и lifecycle
  доступности действий; накопленный набор: 98/98 tests.

## GUI-04 — завершён 2026-10-13

- Добавлен application-level DesktopApplicationAdapter: видимые текстовые
  объекты с собственными pinned style/seed/realism и координатами объединяются
  в один Page, PenPlan, MotionPlan, production/preview SVG и virtual G-code.
- Идентификаторы strokes/source refs namespaced по object ID; слишком длинный
  объект явно отклоняется, пересечение bounds попадает в diagnostics, а
  simulation-only и hardware-unverified сохраняются в отчёте.
- Генерация выполняется через QThreadPool/QRunnable. Одновременно допускается
  одна задача; snapshot и revision захватываются до запуска, устаревший успех
  или ошибка отбрасываются без замены принятого результата.
- Проверены два позиционированных объекта, настоящий background success,
  missing-glyph failure с сохранением холста и stale-result guard; накопленный
  набор: 92/92 tests.

## GUI-03 — завершён 2026-10-13

- Реализован строгий переносимый `hp-desktop-project/1.0`: A4 settings,
  ordered text objects, pinned StylePack revisions, seed/realism и display
  settings. JSON пишется канонически через fsync + atomic replace.
- DocumentController хранит immutable snapshots, монотонную revision, dirty
  state и QUndoStack. Project Explorer действительно добавляет, удаляет,
  переименовывает и скрывает текстовые объекты.
- Properties редактирует текст, позицию в mm, x-height, line pitch, style,
  seed/realism и поля страницы. Все установленные StylePack отображаются как
  проверяемые ресурсы, включая test-only status.
- Round trip Unicode-проекта, неизвестная версия, undo/redo и GUI model actions
  проверены; накопленный набор: 89/89 tests.

## GUI-02 — завершён 2026-10-13

- Центральная сцена использует миллиметры и показывает A4 210×297 с полями,
  тенью бумаги и устойчивым fit-to-page.
- Production и diagnostic SVG загружаются непосредственно из байтов backend;
  travel preview и маркеры начала/конца переключаются только как слои просмотра.
- Добавлены Ctrl+колесо для zoom, Space+drag для pan и отдельные проверки
  физических размеров, SVG rendering и видимости слоёв; накопленный набор:
  85/85 tests.

## GUI-01 — завершён 2026-10-13

- PySide6 6.12.0 подключён только через extras `gui`/`gui-dev`; основной CLI и
  application/core слои не импортируют Qt.
- Добавлена запускаемая команда `hplot-gui` с тёмной Fusion-темой, главным
  окном, меню, строкой состояния и переставляемыми панелями Project Explorer,
  Properties и Output.
- Начальная оболочка проверена через `pytest-qt` на offscreen-платформе вместе
  со всем накопленным набором: 82/82 tests.

## GUI-00 — завершён 2026-10-13

- Проведён аудит текущих application API и зафиксированы границы нового
  `handwriting_plotter.gui`: GUI вызывает application-слой, а экспортируемая
  геометрия остаётся авторитетной.
- В ADR-18 описаны единицы сцены в миллиметрах, immutable snapshot,
  revision-based stale-result guard, атомарный переносимый формат проекта и
  отсутствие ложной отмены, отправки на станок и аппаратных обещаний.
- IMPLEMENTATION_PLAN, MODULE_CONTRACTS, TECH_STACK, TEST_STRATEGY и RISKS
  синхронизированы с этапами GUI-00…GUI-06.

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

### Пилот 0.1.0 — реализован 2026-10-13, gate не снят

- Добавлен `ua-school-v1-pilot`, не являющийся product revision
  `ua-school-v1`: 26 символов и 32 вручную заданных directed centre-line
  variants. Исходный набор задачи дополнен `к`, `ь`, `У` для frozen corpus.
- Все строчные имеют authored baseline entry/exit anchors. `ґ`, `і`, `ї`, `й`
  сохраняют marks отдельными отложенными штрихами. Для `а`, `е`, `и`, `м`,
  `о`, `т` есть по два явных варианта.
- 33 пары в словах `Україна`, `ґрунт`, `мама`, `привіт`, `школа`, `пишу`,
  `ймовірність` проверяются автоматически. Разрешённые lowercase pairs не
  дают join rejection; `У→к` намеренно использует pen lift.
- Anchor tangents теперь сверяются с фактическими производными authored paths;
  partner classes проверяются симметрично, `no_join_before/after` исполняются.
- Полный накопленный набор после изменения: 75/75 tests. SVG/PenPlan/
  MotionPlan/virtual G-code проходят round trip; hardware по-прежнему не
  проверялось.
- Машинный визуальный просмотр выявил сходство плотных hump-форм `и/п/т/ш`.
  Требуются правка художником и V-01/V-02; поэтому BLK-STYLE-001 остаётся.

### Пилот 0.2.0 — реализован 2026-10-13, gate не снят

- Ревизия 0.1.0 сохранена без изменений. В новой ревизии 26 keys и 42
  variants; frozen visual corpus расширен до 12 слов.
- Вручную перерисованы `и`, `п`, `н`, `м`, `т`, `ш`, `щ`, `і`, `ї`, `й`,
  `ґ`. Исправлено соотношение тела к x-height, а marks заново размещены для
  физического размера 3–4 mm.
- Для `п/м/т/ш/щ` есть initial/medial/final context forms. Намеренные pen lifts
  сохраняют характерный вход вместо обязательной универсальной перемычки.
- Все пары frozen corpus проверяются при 3.0, 3.6 и 4.0 mm: случайных geometry
  rejection нет, остаются только явно заданные `JOIN_FORBIDDEN`.
- Полный накопленный набор: 80/80 tests. SVG/PenPlan/MotionPlan/virtual G-code
  проходят round trip; hardware не проверялось.
- Сравнительные A4 SVG и PNG опубликованы в
  `examples/ua-school-pilot-comparison`. Самооценка не закрывает V-01/V-02;
  BLK-STYLE-001 остаётся.

## I-04 — завершён 2026-10-12

- Реализованы CRLF/CR→LF, extended grapheme clusters, per-cluster NFC и карта
  исходных scalar spans без замены похожих символов.
- Tailored LTR policy различает обычные/NBSP/narrow-NBSP пробелы, tab, LF и
  form-feed; запрещённые C0/bidi controls отклоняются с позицией.
- Coverage проверяет весь документ и перечисляет каждую отсутствующую графему,
  code points и исходные spans до layout/export.
- T-U01…T-U06 и весь накопленный набор: 26/26 успешно.

## I-05 — завершён 2026-10-12 для test-only styles

- Longest-match ограничен восемью графемами; source ranges и occurrence IDs
  основаны на исходных grapheme IDs.
- Variant choice и bounded scale/shear/baseline variation получаются из SHA-256,
  не используют `random`, время или Python hash; соседний повтор избегает того же
  variant при наличии альтернативы.
- GlyphFrame преобразуется целиком в WordFrame mm вместе с anchors. Разрешённый
  join строится прямым cubic; script/punctuation/class/gap/vertical/tangent и
  backward-X проверки дают объяснимый pen-lift fallback.
- Body chain выполняется до deferred marks; critical marks не переупорядочиваются
  между словами.
- T-J01…T-J06/T-R01…T-R03 и накопленный набор: 35/35 успешно. T-J07 остаётся
  частью заблокированного pair review настоящего `ua-school-v1`.

## I-06 — завершён 2026-10-12

- PageSpec валидирует физическую область; строки измеряются по реальным
  ink bounds с шириной пера, включая отрицательные bearings и marks.
- Greedy layout повторяет слово на следующей строке без нового occurrence ID;
  oversized token перебирается по grapheme prefixes и reshaping, один слишком
  широкий glyph даёт явную ошибку.
- Реализованы spaces/tab stops, hard/page breaks, NBSP overflow, пустые строки,
  paragraph gap, effective pitch по реальной высоте и многостраничная A4
  пагинация.
- Финальная проверка требует 100% source coverage и bounds внутри printable
  region; никакого clipping или скрытого scale.
- T-L01…T-L07 и накопленный набор: 42/42 успешно.

## I-07 — завершён 2026-10-12

- PenPlan начинается EnsurePenUp; каждая authored execution group компилируется
  как TravelTo→PenDown→Draw→PenUp, word/page checkpoints разрешены только при UP.
- Отдельный state-machine validator проверяет position continuity, pen state,
  уникальные op IDs и финальный page checkpoint; логический симулятор считает
  длины, lifts и flattened segments без физических заявлений.
- Production SVG имеет физический размер A4, viewBox в mm и ровно один path на
  непрерывный контакт, без `<text>`/travel/CSS/font. Preview явно diagnostic и
  добавляет пунктирные travels и номера.
- T-P01…T-P03/T-E01…T-E03 и накопленный набор: 48/48 успешно.

## I-08 — завершён 2026-10-12

- Добавлен единственный профиль `virtual-cartesian-z-v1`, строго
  `simulation_only=true`, с XYZ limits, известным start state, Page→Work
  `(x, 297-y)`, Z pen macro, feeds и settle из DATA_MODELS §6.
- Планировщик выполняет transform→flatten≤0.02 mm→quantize 0.001 mm→повторную
  bounds/state проверку; общий численный budget≤0.05 mm. Схлопнувшийся целиком
  semantic stroke отклоняется.
- Virtual dialect выдаёт только G21/G90/G94, G1 с явным F и G4 P; XY и Z не
  смешиваются. Независимый parser отвергает G0/M-коды, control injection,
  неизвестные axes/слова и сравнивает decoded geometry с раскрытым MotionPlan.
- T-M01…T-M07 и накопленный набор: 58/58 успешно. Реального machine profile,
  transport или sender нет.

## I-09 — программная реализация завершена, продуктовый gate заблокирован I-03

- CLI предоставляет `inspect`, `generate`, `export`, `simulate` и
  `styles validate`; библиотека и CLI вызывают один application service.
- `test-technical-v1` содержит 189 явно test-only glyph keys и полный
  обязательный набор UA/RU/EN/цифр/пунктуации. Это читаемый технический
  single-line small-caps fixture, не заявка на школьную скоропись.
- Bundle публикуется через staging/atomic rename и содержит input/request,
  pinned style, PenPlan, production/preview SVG, MotionPlan, virtual G-code,
  report и SHA-256 manifest. Ошибка покрытия на последней графеме не создаёт
  output; одинаковые pinned inputs дают byte-identical artifacts.
- Wheel установлен в чистое CPython 3.12.12 окружение; после установки полный
  `inspect` и `simulate` выполнены без сетевых обращений и без imports
  serial/SVG/ML.
- Benchmark на AMD Ryzen 5 PRO 4650U: 19 999 графем, 10 страниц, 17.401 s,
  peak RSS 277 996 KiB; цель ≤30 s/≤512 MiB выполнена.
- После негативного архитектурного аудита усилены nested SVG transforms/depth,
  StylePack review/hash/envelope checks, connector clearance, NBSP grouping,
  exact XYZ profile и decoded bounds; накопленный набор: 69 tests. Финальное
  имя release остаётся «software validated with test-only style; hardware
  unverified». Продуктовый I-09 не закрывается до BLK-STYLE-001.

