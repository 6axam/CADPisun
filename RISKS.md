# Риски, реализуемость и будущие проверочные эксперименты

v1.0 · 2026-10-12. **Ни один эксперимент этого документа сейчас не выполнялся.** Подтверждение существования метода/исходника не равно проверке готового приложения. Evidence: [RESEARCH.md](RESEARCH.md); критерии: [TEST_STRATEGY.md](TEST_STRATEGY.md).

## 1. Уровни уверенности

| Утверждение | Статус | Основание / остающийся предел |
|---|---|---|
| Можно хранить и экспортировать направленные single-line strokes | Подтверждено | Реальные SVG/path/capture implementations; корректность нашего будущего кода ещё проверяется |
| Unicode keys могут покрыть UA/RU/EN | Подтверждено | Формат допускает эти графемы; сами нужные glyph assets ещё нужно создать |
| У пяти кандидатов есть готовый качественный полный UA cursive набор | Не подтверждено, открытый риск | Проверенный HersheyCyrillic не покрывает нужные буквы; VHS sample не доказал UA coverage |
| Авторский набор + anchors способен дать читаемую UA скоропись | Предположительно реализуемо | Конструктивный план со штрихами; визуальный результат зависит от данных, E-01/E-02 |
| Можно соединять произвольные буквы коротким Bézier | В общем виде неверно | Только совместимые authored endpoints; остальное lift/ligature/redraw |
| Страница после bounded variation может оставаться в пределах | Подтверждено как проверяемый алгоритмический контракт | Измерять после variations и повторно валидировать, E-03 |
| Skeletonization даёт центральную топологию маски | Подтверждено | skimage; шум, junctions, dots всё ещё требуют review |
| Контур чернил равен пути ручки | Неверно | `findContours`/outline tracing дают другое представление |
| Из одного фото можно всегда точно восстановить порядок/время | В общем случае невозможно | Несколько разных движений дают одинаковую конечную картинку; дополнительных наблюдений нет |
| Можно получить полезную правдоподобную trajectory hypothesis из фото | Подтверждено исследовательскими примерами, качество на UA открыто | InkSight/TRACE; локальный production gate E-07/E-08 |
| HTR современного личного конспекта будет сразу точным | Открытый риск | Domain shift, почерк, снимок, line segmentation, codec; E-06 |
| Можно подготовить корректный G-code без реального станка | Подтверждено только для заданного виртуального/документированного dialect | Нельзя подтвердить неизвестную firmware/actuator; E-04/E-05 |
| Архитектура адаптируема к нескольким контроллерам | Предположительно реализуемо | Отделены frames/backend/transport; конкретный controller требует своего adapter и HIL |
| Обычная ручка воспроизведёт pressure/style как экран | Открытый риск | Давление, трение, ink flow, paper, width и acceleration неизвестны |

## 2. Реестр рисков

| ID | Риск / важность | Мера снижения и stop condition | Проверка |
|---|---|---|---|
| K01 | Некачественный стартовый почерк — критический | Data-first pilot; нет release до review, не маскировать Hershey под курсив | E-01, V-01 |
| K02 | Соединения портят форму/пересекают соседей — высокий | Anchors, class rules, bounded cubic, clearance veto, lifted fallback | E-02, T-J |
| K03 | Длинные слова/вариации ломают поля — высокий | Measure final words, correct context reshape, final bounds, no clip | E-03, T-L |
| K04 | Неправильный pen sequence/G-code — критический | Общий IR, typed dialect, independent decoder, all-travel checks | E-04, T-P/T-E/T-M |
| K05 | Неизвестный actuator/кинематика — критический для I-H | Profile capability gate, registration/calibration, no guessed values | E-05, H-A…H-D |
| K06 | ACK ошибочно принят за исполнение, unsafe retry — критический | Session FSM, accepted/executed distinction, checkpoint journal | T-H02/T-H03 |
| K07 | CV теряет dots/путает lines — высокий | Original immutable, masked crop review, per-character metrics | E-06, T-C02 |
| K08 | Реконструкция выдаёт уверенную неверную историю — высокий | Alternatives, unknown confidence, online capture предпочтительнее | E-07/E-08 |
| K09 | Зависимости несовместимы/нет wheels — средний | Base lock gate; отдельные vision/HTR/InkSight envs | I-00, II gates |
| K10 | Неподходящие лицензии/assets — высокий | Separate rights records, собственный default style, no unlicensed copy | T-S01/T-D05 |
| K11 | ML слишком тяжёл для ноутбука — средний/высокий | CPU benchmark, manual baseline, no mandatory cloud, optional feature | E-06/E-07 |
| K12 | Формат внешнего проекта меняется — средний | Pinned source revision, narrow importer, own immutable schema | Adapter fixtures/unknown-version failure |
| K13 | Данные автора/конспекты утрачены или смешаны — высокий | Content hashes, backups/migrations, transactional corrections, profile namespaces | T-D02/T-D04 |
| K14 | Установка одинакового seed не даёт равного output — средний | Hash-based choices, versioned algorithm, pinned artifacts/lock | T-R01 |
| K15 | Quantization/слишком много segments — высокий | Error budget, limit checks, no silent dropped marks | T-G02/T-M04/T-A04 |
| K16 | Объём scope растёт до GUI/ML до работающего письма — высокий | Последовательные I gates, отдельные II/III, отсутствие GUI package | План пакетов и release checklist |

## 3. Проверочные эксперименты для следующего этапа

### E-01 — техническая/визуальная пригодность собственного UA стиля

До полного набора изготовить 20 критичных glyphs и 50 коротких слов/пар; среди них ґ/є/і/ї/й/т/ш/щ и апостроф. Отрисовать centerline paths и anchors без CV/нейросетей. Сравнить с референсным письмом автора в x-height3.5mm.

Успех: complete tested coverage, читаемость≥98% у3 читателей, отсутствие систематически ошибочных форм/потерянных marks, набор можно последовательно аннотировать directed body/marks. Если критерий не выполнен — исправить набор/привлечь автора для формы. Не расширять модель случайными шумами. Эксперимент может показать, что нужен другой authoring process, но не опровергает архитектуру.

### E-02 — соединения и регулярность почерка

Corpus200 pair instances покрывает все используемые классы входа/выхода, повторяющиеся буквы и boundary exceptions; минимум100 новых слов, отдельные min/max размеры и10 seeds. Freeze corpus до подбора параметров, оставить held-out words.

Успех: ноль illegal crossings/случайных word joins, ≥90% intended joins на frozen допустимом subset, V-02≥4/5, readable protected characters. При провале — корректировать anchors/variants/ligatures, допускать осмысленные lifts. Класс pair, которому нужен сложный loop, не лечить глобальным повышением max_gap.

### E-03 — layout/geometry стресс

Собственный corpus10 страниц,100 seeds, крайние принятые размеры, tight margins, curved tails, long words, explicit breaks. Измерять производительность на записанном host.

Успех:100% source coverage,0 ink out-of-bounds,0 invalid state, endpoint/flatten budget выдержан; unsupported oversized случаи возвращают документированную ошибку. Target20k графем≤30s/512MiB; при превышении — профилировать shapes/cache/flatten, не внедрять ML/GPU. Численные проверки выполняются только при будущей реализации.

### E-04 — экспорт и симуляция команд

Сгенерировать virtual MotionPlan fixtures с Z-lifts/settle, экстремумами, очень короткими marks и page edges. Независимый parser реконструирует modality и geometries. Inject forbidden command/control text в отрицательные fixtures.

Успех: order/pen transitions точно совпадают; deviation≤0.05mm; все travel/actuation bounds валидны; malformed codes rejected; virtual output не может быть отправлен real session. Это gate программного MVP, не тест станка.

### E-05 — адаптация к реальному оборудованию

Только после Q-H. Подтвердить firmware identity, units/origin, mapping пера и sync. Начать с pen-up travel, затем calibration figure, pen lifts, короткие слова и длительное задание. Сканировать/измерить output относительно page registration, не только смотреть на движение.

Успех: согласованные H-A…H-D, нет ink во время travel, нет столкновения/пропуска шагов в принятом режиме, предварительный target repeatability≤0.2mm либо заранее документированный пересмотр под измеренную механику. При несовместимости firmware/actuator остановить hardware release; geometry/SVG остаются работоспособны. Ограничения включают крепление листа и смену страницы.

### E-06 — качество локального CV/HTR

Использовать corpus II-01; сравнить ручные line crops, автоматические polygons и разные допустимые HTR candidates на одном held-out subset. Измерить CER/WER, rare letters, line misses, CPU latency/RAM, время ручной correction. Printed OCR не использовать в качестве единственного baseline рукописи.

Успех: line F1≥0.95 на flat-page subset, CER≤10% initial target, protected chars не теряются систематически, все модели/данные имеют проверенные rights/codec. Practical latency target≤5s/line на описанном CPU и peak RAM≤4GiB; при недостаточной RAM пользователя параметр уточняется перед запуском, не предполагается сейчас. При провале оставить ручную segmentation/transcription и/или расширить data; UI/генератор не переписывать.

### E-07 — InkSight compatibility и полезность

Сначала reproduce официальный inference fixture с pinned checkpoint и выбранной TF-конфигурацией; зафиксировать, какая часть старой card/new code рекомендаций действительно нужна. Затем минимум100 paired words, сравнение с manual/skeleton baseline. Отдельно проверить кириллицу и апострофы. CPU окружение не должно требовать CUDA.

Успех: стабильные outputs, нет missing critical marks/text changes после review, manual correction time снижается≥25% без ухудшения качества, память/время приемлемы на измеренном устройстве. Для inferred directions не заявлять истинность без paired traces. При провале не включать feature; этот эксперимент не блокирует этап I/II-A.

### E-08 — reconstruction ambiguity и качество sample library

Constructed paired dataset содержит crossings, loops, retracing, disconnected marks и одинаковые raster images разных online sequences. Проверить graph hypotheses, ручные split/merge/order edits, нормализацию нового glyph и повторное письмо новых слов.

Успех: неоднозначность отражена в данных,0 автоматически утверждённых ложных captured orders; accepted samples проходят geometry/coverage/critical-feature checks, median centerline error≤1px на нормализованном оценочном наборе после review. Для истинного order измерить отдельные метрики на online subset без обязательства точного recovery всех фото. Экономический gate: стоимость ручной коррекции меньше повторного ввода clean online samples; иначе предпочесть online capture.

## 4. Вопросы, которые действительно блокируют соответствующие этапы

### Q-S — до публикации готового почерка I-03

- Кто создаёт/предоставляет стартовые авторские central-line glyphs и на каких условиях их можно распространять?
- Какая конкретная style revision получила V-01/V-02 review? Это ответ артефактом/протоколом, не просто предпочтение названия шрифта.

Программные I-00/I-01/I-02 и тестовые fixtures могут создаваться без этих ответов. Готовый MVP нельзя выпустить без реальных данных и review. В этой архитектурной задаче не требуется немедленный ответ пользователя.

### Q-H — до real machine profile и I-H

- Кинематика, рабочие axes/единицы, полезное поле, forbidden zones, home/origin, soft/hard limits и способ подтверждать позицию.
- Контроллер/firmware/version, фактический dialect, queued motion/pen synchronization, status/hold/reset/abort semantics.
- Механизм пера: Z, servo, digital или иной; контакт/clearance, polarity/диапазон, settling, fail-safe при обрыве связи/питания.
- Transport и соединение: serial/USB/network, подтверждённые параметры, размер буфера, flow control.
- Ручка/бумага/фиксация, реальная ширина линии, допустимые скорости/ускорения и результаты калибровки.

Ответы неизвестны; virtual профиль не подставляется вместо них. Ни один из этих вопросов не блокирует документацию и программный MVP.

### Q-D — до private data ingestion/training II

- Есть ли разрешённые собственные страницы и возможность получить online samples? Фото, traced-by-reviewer и настоящая запись автора имеют разные provenance.
- Какие язык/почерк/качество снимков образуют целевой corpus, есть ли контрольные непересекающиеся сессии?
- Какие RAM/GPU/время доступны фактически, какие datasets/models прошли license и codec review?

Если online hardware отсутствует, разрешены авторские SVG и ручная коррекция; нельзя обещать извлечь всю неизвестную динамику из фото. Выбор pretrained weights блокируется corpus benchmark, а не весь design.

## 5. Рациональные альтернативы при неуспехе

Неудачная автоматическая реконструкция → чистые online записи или ручные centerline glyphs. Неудачные universal joins → больше authored ligatures и локальные lifts. Тяжёлый HTR → ручные transcriptions и небольшая модель позже. Неизвестный контроллер → проверенный SVG/PenPlan и внешний sender после аппаратной проверки. Недостаточное рабочее поле → понятная ошибка профиля и явное изменение page settings, не скрытое сжатие.

Эти варианты сохраняют главную цель: воспроизводимые физические траектории читаемого текста. Они не требуют возвращаться к контурным TTF или выбрасывать общее ядро.
