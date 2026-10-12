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
- Накопленный автоматический набор после добавления E2E: 64 tests. Финальное
  имя release остаётся «software validated with test-only style; hardware
  unverified». Продуктовый I-09 не закрывается до BLK-STYLE-001.

