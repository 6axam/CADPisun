# Установка Handwriting Plotter из GitHub ZIP

Эта инструкция рассчитана на человека, который впервые открывает терминал.
Git устанавливать не нужно: проект скачивается обычным ZIP-архивом.

## Быстрая навигация

- [Windows 10/11 — PowerShell](#windows-1011--powershell)
- [Arch Linux / Omarchy — Bash](#arch-linux--omarchy--bash)
- [Ubuntu — Bash](#ubuntu--bash)
- [Обновление через GitHub](#обновление-до-новых-коммитов-через-github)
- [Проверка установки](#как-понять-что-установка-завершена)
- [Частые ошибки](#частые-ошибки)

Все команды находятся в отдельных блоках. На GitHub у каждого такого блока
есть кнопка копирования в правом верхнем углу. Скопируйте команду, вставьте её
в терминал и нажмите Enter. В Windows Terminal вставка работает через
Ctrl+Shift+V, в большинстве Linux-терминалов — также через Ctrl+Shift+V.

> [!IMPORTANT]
> Для проекта требуется **64-битная система**, доступ в интернет и примерно
> 1 ГБ свободного места. Первая установка загружает Python, PySide6/Qt и другие
> зависимости. Следующие запуски работают из уже созданного окружения.

## Что будет установлено

- `uv` — программа, которая установит Python и зависимости проекта;
- управляемый `uv` Python **3.12.12**;
- зависимости из `uv.lock`, включая **PySide6 6.12.0**;
- локальное окружение `.venv` внутри распакованной папки проекта.

Системный Python менять не требуется. Все команды установки проекта нужно
выполнять в папке, где находятся `pyproject.toml`, `uv.lock` и `README.md`.

## Скачать ZIP

1. Откройте страницу [6axam/CADPisun](https://github.com/6axam/CADPisun).
2. Нажмите зелёную кнопку **Code**.
3. Выберите **Download ZIP**.
4. Дождитесь загрузки файла `CADPisun-main.zip`.

Можно использовать [прямую ссылку на ZIP ветки main](https://github.com/6axam/CADPisun/archive/refs/heads/main.zip).

---

## Windows 10/11 — PowerShell

> [!NOTE]
> Windows-версия приложения ещё не проходила полный тест на реальном Windows
> компьютере. Шаги основаны на официальном установщике `uv`, Windows wheels
> закреплённых зависимостей и фактических командах проекта. Если возникнет
> ошибка, используйте раздел [Частые ошибки](#частые-ошибки).

### 1. Распакуйте проект

1. Откройте папку **Загрузки** в Проводнике.
2. Щёлкните правой кнопкой по `CADPisun-main.zip`.
3. Выберите **Извлечь всё…**.
4. Откройте распакованную папку `CADPisun-main`.

Не запускайте проект прямо внутри ZIP. Папка должна быть полностью распакована.

### 2. Откройте PowerShell в папке проекта

На Windows 11 щёлкните правой кнопкой по пустому месту внутри папки и выберите
**Открыть в терминале**. На Windows 10 нажмите адресную строку Проводника,
введите `powershell` и нажмите Enter.

Убедитесь, что PowerShell открыт в правильной папке:

```powershell
Test-Path .\pyproject.toml
```

Команда должна вывести `True`. Если она вывела `False`, перейдите в
распакованную папку вручную. Пример для стандартной папки загрузок:

```powershell
Set-Location "$HOME\Downloads\CADPisun-main"
```

Снова проверьте наличие файла:

```powershell
Test-Path .\pyproject.toml
```

### 3. Установите uv

Вставьте официальную команду установки `uv` в PowerShell и нажмите Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Закройте окно PowerShell и откройте его снова в папке проекта. Проверьте
установку:

```powershell
uv --version
```

Если Windows пишет, что команда `uv` не найдена, временно добавьте стандартную
папку установщика в `PATH` текущего окна:

```powershell
$env:Path = "$HOME\.local\bin;$env:Path"
```

Повторите проверку:

```powershell
uv --version
```

Если политика организации полностью блокирует PowerShell-скрипты, установите
`uv` через WinGet:

```powershell
winget install --id=astral-sh.uv -e
```

После WinGet также закройте и заново откройте терминал.

### 4. Установите Python 3.12.12

`uv` установит отдельный управляемый Python, не затрагивая другие программы:

```powershell
uv python install 3.12.12
```

Проверьте, что точная версия найдена:

```powershell
uv python find 3.12.12
```

Команда должна вывести путь к интерпретатору Python 3.12.12.

### 5. Установите Handwriting Plotter и PySide6

Убедитесь, что терминал всё ещё находится в папке `CADPisun-main`, затем
выполните основную команду проекта:

```powershell
uv sync --python 3.12.12 --extra gui
```

`uv` создаст папку `.venv` и установит зависимости из `uv.lock`. Отдельно
запускать `pip install PySide6` не нужно.

При желании проверьте установленную версию PySide6:

```powershell
uv run python -c "import PySide6; print(PySide6.__version__)"
```

Ожидаемая версия — `6.12.0`.

### 6. Запустите GUI

```powershell
uv run hplot-gui
```

Должно открыться окно **Handwriting Plotter**. Терминал остаётся открытым, пока
работает приложение. Это нормально. Для остановки закройте окно программы.

### Повторный запуск на Windows

После первой установки повторно устанавливать Python и зависимости не нужно.
Откройте PowerShell в распакованной папке и выполните:

```powershell
uv run hplot-gui
```

Если PowerShell открыт в другой папке, сначала перейдите к проекту:

```powershell
Set-Location "$HOME\Downloads\CADPisun-main"
```

---

## Arch Linux / Omarchy — Bash

Handwriting Plotter разрабатывался и проверялся на Linux/Omarchy с Wayland.

### 1. Подготовьте системные инструменты

Откройте терминал и установите `curl` и `unzip`, если их ещё нет:

```bash
sudo pacman -S --needed curl unzip
```

### 2. Распакуйте ZIP

ZIP можно распаковать через файловый менеджер командой **Extract here**.
Для распаковки через терминал перейдите в папку загрузок:

```bash
cd ~/Downloads
```

Распакуйте архив:

```bash
unzip CADPisun-main.zip
```

Перейдите в папку проекта:

```bash
cd CADPisun-main
```

Проверьте, что это корень проекта:

```bash
test -f pyproject.toml && echo "Папка проекта найдена"
```

### 3. Установите uv

Используйте официальный Bash-установщик:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Закройте и снова откройте терминал. Либо добавьте установленный `uv` в `PATH`
текущего терминала:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Проверьте установку:

```bash
uv --version
```

### 4. Установите Python 3.12.12

```bash
uv python install 3.12.12
```

Проверьте найденный интерпретатор:

```bash
uv python find 3.12.12
```

### 5. Установите зависимости GUI

Выполните команду в папке `CADPisun-main`:

```bash
uv sync --python 3.12.12 --extra gui
```

Проверьте PySide6:

```bash
uv run python -c "import PySide6; print(PySide6.__version__)"
```

### 6. Запустите приложение

```bash
uv run hplot-gui
```

В Wayland-сессии Omarchy Qt обычно выбирает нужный backend автоматически. Если
окно не появляется, попробуйте явный запуск через Wayland:

```bash
QT_QPA_PLATFORM=wayland uv run hplot-gui
```

### Повторный запуск на Arch/Omarchy

Откройте терминал, перейдите в папку проекта:

```bash
cd ~/Downloads/CADPisun-main
```

Запустите GUI:

```bash
uv run hplot-gui
```

---

## Ubuntu — Bash

Инструкция подходит для обычной графической сессии Ubuntu. Текущая сборка не
проверялась на каждой версии Ubuntu, поэтому при проблемах с Qt используйте
раздел диагностики ниже.

### 1. Подготовьте системные инструменты

Обновите список пакетов:

```bash
sudo apt update
```

Установите `curl` и `unzip`:

```bash
sudo apt install -y curl unzip
```

### 2. Распакуйте проект

Можно открыть `CADPisun-main.zip` в файловом менеджере и выбрать
**Extract Here**. Для терминала перейдите в загрузки:

```bash
cd ~/Downloads
```

Распакуйте ZIP:

```bash
unzip CADPisun-main.zip
```

Откройте папку проекта:

```bash
cd CADPisun-main
```

Проверьте корень проекта:

```bash
test -f pyproject.toml && echo "Папка проекта найдена"
```

### 3. Установите uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Закройте и заново откройте терминал или обновите `PATH` текущего окна:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Проверьте результат:

```bash
uv --version
```

### 4. Установите Python 3.12.12

```bash
uv python install 3.12.12
```

Проверьте путь к Python:

```bash
uv python find 3.12.12
```

### 5. Установите GUI-зависимости

```bash
uv sync --python 3.12.12 --extra gui
```

Проверьте PySide6:

```bash
uv run python -c "import PySide6; print(PySide6.__version__)"
```

### 6. Запустите приложение

```bash
uv run hplot-gui
```

Если Ubuntu работает в Wayland-сессии и автоматический выбор не сработал:

```bash
QT_QPA_PLATFORM=wayland uv run hplot-gui
```

Если используется X11 или XWayland:

```bash
QT_QPA_PLATFORM=xcb uv run hplot-gui
```

### Повторный запуск на Ubuntu

```bash
cd ~/Downloads/CADPisun-main
```

```bash
uv run hplot-gui
```

---

## Как понять, что установка завершена

В корне проекта появится папка `.venv`. Проверка среды должна вывести Python
3.12.12:

### PowerShell

```powershell
uv run python --version
```

### Bash

```bash
uv run python --version
```

Запуск GUI на всех системах выполняется одной командой:

```text
uv run hplot-gui
```

## Частые ошибки

### `uv` не найден

Сначала полностью закройте терминал и откройте его заново.

PowerShell, временное исправление для текущего окна:

```powershell
$env:Path = "$HOME\.local\bin;$env:Path"
```

Bash, временное исправление для текущего окна:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Проверьте:

```text
uv --version
```

### `No pyproject.toml found` или запускается не тот проект

Терминал открыт не в корне распакованного проекта.

PowerShell:

```powershell
Test-Path .\pyproject.toml
```

Bash:

```bash
test -f pyproject.toml && echo OK
```

Результат должен быть `True` или `OK`. Перейдите в папку `CADPisun-main` и
повторите команду запуска.

### Не удалось скачать Python 3.12.12

Обновите `uv`:

```text
uv self update
```

Повторите установку Python:

```text
uv python install 3.12.12
```

Для загрузки нужны доступ к `astral.sh`, GitHub и серверу дистрибутивов
`python-build-standalone`. Корпоративный proxy или антивирус может блокировать
эти адреса.

### Ошибка установки зависимостей или повреждённый кэш

Обновите загружаемые пакеты и повторно синхронизируйте окружение:

```text
uv sync --refresh --python 3.12.12 --extra gui
```

Проверьте импорт Qt:

```text
uv run python -c "import PySide6; print(PySide6.__version__)"
```

### Linux: ошибка `Could not load the Qt platform plugin "xcb"`

На Arch/Omarchy установите основные runtime-библиотеки XCB:

```bash
sudo pacman -S --needed libxcb xcb-util-cursor libxkbcommon
```

На Ubuntu установите основные runtime-библиотеки Qt/XCB:

```bash
sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1
```

После установки попробуйте Wayland:

```bash
QT_QPA_PLATFORM=wayland uv run hplot-gui
```

Или XCB/XWayland:

```bash
QT_QPA_PLATFORM=xcb uv run hplot-gui
```

### Linux: `could not connect to display`

GUI запускается только внутри графической сессии. Откройте локальный терминал
на рабочем столе Linux. При подключении только через SSH без настроенного
графического forwarding окно не откроется.

Проверьте тип текущей сессии:

```bash
echo "$XDG_SESSION_TYPE"
```

### Windows: окно сразу закрывается или Qt не импортируется

Запустите приложение из PowerShell, не двойным щелчком, чтобы увидеть ошибку:

```powershell
uv run hplot-gui
```

Проверьте PySide6 отдельно:

```powershell
uv run python -c "import PySide6; print(PySide6.__version__)"
```

Обновите окружение:

```powershell
uv sync --refresh --python 3.12.12 --extra gui
```

Если путь к проекту содержит необычные символы и ошибка сохраняется, распакуйте
ZIP в короткий путь, например `C:\HandwritingPlotter`, и повторите установку.

### Команда `hplot-gui` не найдена

Убедитесь, что команда выполняется в папке проекта, и снова установите extra
`gui`:

```text
uv sync --python 3.12.12 --extra gui
```

Затем повторите:

```text
uv run hplot-gui
```

## Обновление до новых коммитов через GitHub

Git не нужен и для обновления. ZIP ветки `main` содержит состояние проекта на
последнем коммите, который был отправлен в GitHub к моменту скачивания.

### 1. Посмотрите последние изменения

Откройте [историю коммитов ветки main](https://github.com/6axam/CADPisun/commits/main).
Самый верхний коммит — текущая версия проекта. Короткий набор символов рядом с
ним, например `a1b2c3d`, является коротким номером коммита.

Чтобы посмотреть конкретное изменение, нажмите его название. На странице
коммита GitHub показывает изменённые файлы и полный номер коммита.

### 2. Сохраните свои файлы

Закройте Handwriting Plotter. Если ваши проекты `*.hplot.json`, SVG или G-code
лежат внутри старой папки `CADPisun-main`, скопируйте их в **Документы** или
другую личную папку. Не храните единственную копию своих работ внутри папки,
которую собираетесь заменить.

Папку `.venv` переносить не нужно. Она будет заново создана из `uv.lock`.

### 3. Скачайте последние коммиты

1. Откройте [главную страницу проекта](https://github.com/6axam/CADPisun).
2. Нажмите **Code**.
3. Выберите **Download ZIP**.
4. Полученный `CADPisun-main.zip` распакуйте в **новую папку**.

Можно сразу открыть [ZIP последнего коммита ветки main](https://github.com/6axam/CADPisun/archive/refs/heads/main.zip).

> [!IMPORTANT]
> Не распаковывайте новый архив поверх старой папки: удалённые или
> переименованные разработчиками файлы могут остаться там и вызвать ошибки.
> Старую папку можно удалить только после успешного запуска новой версии и
> проверки сохранённых проектов.

Если нужна не последняя версия, а конкретный коммит, откройте его в
[истории коммитов](https://github.com/6axam/CADPisun/commits/main), нажмите
**Browse files**, затем **Code → Download ZIP**. Имя распакованной папки будет
содержать полный номер выбранного коммита.

### 4. Обновите зависимости в новой папке

Откройте PowerShell или Bash именно в новой распакованной папке. Команда
`uv sync` сравнит новый `uv.lock` с окружением и установит подходящие версии
зависимостей.

### PowerShell

```powershell
Test-Path .\pyproject.toml
```

Команда должна вывести `True`. Затем выполните:

```powershell
uv sync --python 3.12.12 --extra gui
```

```powershell
uv run hplot-gui
```

### Bash

```bash
test -f pyproject.toml && echo "Папка проекта найдена"
```

Затем выполните:

```bash
uv sync --python 3.12.12 --extra gui
```

```bash
uv run hplot-gui
```

### 5. Верните свои проекты

Файлы `*.hplot.json` можно открывать из любой личной папки: переносить их в
исходный код проекта необязательно. После успешного запуска новой версии
откройте нужный файл через **File → Open**.

Для следующего обновления повторите эти же шаги: проверьте верхний коммит на
GitHub, скачайте новый ZIP `main`, распакуйте его отдельно и снова выполните
`uv sync`.

## Официальные справочные материалы

- [Установка uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Установка Python через uv](https://docs.astral.sh/uv/guides/install-python/)
- [Qt for Linux — системные зависимости](https://doc.qt.io/qtforpython-6/overviews/qtdoc-linux-requirements.html)
- [Qt for Wayland — требования](https://doc.qt.io/qtforpython-6/overviews/qtdoc-wayland-requirements.html)
