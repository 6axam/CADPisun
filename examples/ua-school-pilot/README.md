# Визуальный образец украинского пилота

`page-0001.svg` — production SVG без текста, шрифтов и диагностических
перемещений. `page-0001.preview.svg` добавляет только диагностические travel
линии и номера операций. `review.png` — растровый рендер production SVG на
белом фоне для быстрого просмотра.

Образец воспроизводится из `input.txt` с параметрами:

```sh
uv run hplot generate examples/ua-school-pilot/input.txt /tmp/ua-school-review \
  --style ua-school-v1-pilot --style-revision 0.1.0 \
  --seed 20261013 --realism 0 --x-height-mm 4.0 --line-pitch-mm 10
```

Это review artifact. Он подтверждает прохождение SVG/PenPlan/MotionPlan/virtual
G-code, но не заменяет человеческую приёмку формы букв и пробу на станке.
