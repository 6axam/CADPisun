# Сравнение украинского пилота 0.1.0 и 0.2.0

Обе колонки построены одним движком, одним seed и без runtime variation:

- A4, поля 15 mm;
- `x-height=3.6 mm`;
- line pitch 8.5 mm;
- pen width 0.35 mm;
- frozen corpus из 12 слов в `input.txt`.

Файлы:

- `before-0.1.0.svg` и `after-0.2.0.svg` — production SVG без fonts,
  `<text>` и travel moves;
- соответствующие PNG — одинаковые crops для просмотра в реальном масштабе;
- `comparison.png` — колонки до/после рядом.

В 0.2.0 тело строчных занимает примерно 650–720 GU вместо 380–470 GU.
`и/п/н` и `м/т/ш/щ` больше не создаются из одного Bézier-шаблона. Для
`п/м/т/ш/щ` medial/final context допускает намеренный подъём пера перед
характерным начальным элементом: отсутствие connector не растягивает форму и
помогает сохранить границу буквы.

Команда воспроизведения одной колонки:

```sh
uv run hplot generate examples/ua-school-pilot-comparison/input.txt /tmp/ua-v020 \
  --style ua-school-v1-pilot --style-revision 0.2.0 \
  --seed 20261013 --realism 0 --x-height-mm 3.6 --line-pitch-mm 8.5
```

Это инженерное визуальное сравнение. Оно не закрывает V-01/V-02 и не
подтверждает читаемость незнакомого текста независимыми людьми.
