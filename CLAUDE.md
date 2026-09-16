# CV Fitness

Софт для спортивных тренировок: клиент заливает видео, сервер бьёт его на сегменты
упражнений, накладывает скелет позы отдельным слоем (для просмотра без мощного
телефона), добавляет описания и субтитры по сегментам.

Два независимых куска в одном репозитории:

- **`js/` + `index.html`** — исходный браузерный тренажёр позы (клиентский
  MediaPipe, без бэка). Режимы «Один» и «Сравнение», см. корневой `README.md`.
- **`server/`** — FastAPI-бэк и админка для нового потока: заливка → серверная
  обработка → плеер. Это активная зона разработки.

## server/ — стек и конвенции

FastAPI + SQLAlchemy + Postgres + Jinja2 + Tailwind (CDN) + Lucide (CDN, иконки —
`data-lucide="..."` + `lucide.createIcons()`, не emoji/unicode-глифы, они ломаются
на части систем). Всё в Docker Compose.

Запуск:
```
cd server && docker compose up -d
```
Публичный лендинг — `http://localhost:8000/`, кабинет тренера — `/app`. После правок в `app/` — пересобрать образ,
`docker compose up -d` не подхватывает изменения кода без билда:
```
docker compose build web && docker compose up -d --force-recreate --no-deps web
```
`--no-deps` обязателен — иначе пересоздаст и `db` (stateful, с named volume).

`docker compose restart` НЕ перечитывает `env_file`/`.env` — после смены `server/.env`
нужен `up -d --force-recreate --no-deps web`.

### Дизайн

Светлая тема в духе `omra.bill` (таблицы/список), тёмный сайдбар с палитрой из
`../omra.blob/src/omra_blob/admin/static/admin.src.css` («Linear Sublime» dark
theme): surface `#101113`, line `#1f2023`, ink `#f7f8f8`, muted `#8a8f98`, accent
**violet `#8b5cf6`** (не red/rose — это акцент их light-темы, не dark). Карточки
клипов/таймлайн сегментов — референс ClipMaker.

### Известные грабли (не наступать повторно)

- **VFR-видео**: телефонные ролики часто имеют переменную частоту кадров
  (`r_frame_rate` контейнера ≠ `avg_frame_rate`). Таймкод кадра — **всегда**
  `cap.get(cv2.CAP_PROP_POS_MSEC)`, никогда `idx / fps` — константный шаг даёт
  дрейф скелета до нескольких секунд на длинном видео.
- **Global GZipMiddleware ломает видео-Range-стриминг** — gzip сжимает
  бинарный `video/mp4` и портит `Content-Range`/`Content-Length`, видео
  перестаёт декодироваться. Gzip — только точечно на JSON-эндпоинтах
  (`api.py`, ручной `gzip.compress` + заголовок), никогда не глобальный
  middleware в `main.py`.
- **Эта версия Starlette `FileResponse` не поддерживает `Range`-заголовки** —
  для видео используется свой `_range_response` в `api.py`. Без него нет
  перемотки в `<video>`.
- **Трек скелета — компактный формат**: только 13 точек, нужных для 2D-отрисовки
  (без `z`, без лица/пальцев/пяток), плоский массив `[t,x,y,v,...]`, округление
  до 3 знаков. Полный набор из 33 точек с dict-ключами весил 106MB на 35-минутное
  видео — неюзабельно на телефоне. Не возвращаться к dict-формату без причины.
- **Сегментация — Python-порт `js/signature.js` + `js/seg.js`**
  (`app/workers/signature.py`), 1:1 с оригиналом. Меняя логику сегментации —
  синхронизировать оба файла или явно решить, что порт становится
  самостоятельным (и написать почему).

### Секреты

`server/.env` — gitignored, содержит `OPENROUTER_DSN` в формате
`openai://<key>@openrouter.ai/api/v1/<model>` (ключ+модель одной строкой, тот
же формат DSN, что в других проектах флота, напр. `finradar/.env`). Никогда не
коммитить `.env`, не логировать значение ключа целиком.

### Описания сегментов

`app/workers/describe.py` — по превью-кадру каждого сегмента через OpenRouter
(`google/gemini-2.5-flash` по умолчанию — достаточно для короткого описания
позы/упражнения, топовая модель не нужна). Пишет только в пустые `description`,
повторный запуск не тратит деньги на уже описанные сегменты. Кнопка «Описать
сегменты» в `/app/{video_id}`.

## Production

Хост для `omra.fitness` подготовлен на Proxmox-ноде `zaurus`: unprivileged LXC
`169` (`omra-fitness`), внутренний адрес `10.10.11.169/24`, gateway
`10.10.11.1`. Ресурсы: 8 vCPU, 16 GB RAM, 1 GB swap, 100 GB ZFS. Контейнер
запускается вместе с хостом; рабочий каталог — `/opt/omra.fitness`.

В контейнере Debian 12, Docker Engine и Compose plugin. Docker настроен с
`live-restore` и ротацией `json-file` 50 MB × 3; автоматические security updates
включены. Production Compose живёт в `/opt/omra.fitness/server`, приложение
слушает только `10.10.11.169:8000`, Postgres — только во внутренней Docker-сети.
Секреты находятся в `/opt/omra.fitness/server/.env` с режимом `0600`.

Caddy-gateway в LXC 100 проксирует `omra.fitness` на `10.10.11.169:8000`.
Production callback `https://omra.fitness/auth/callback` зарегистрирован в
`omra.is`; серверные OIDC-запросы идут напрямую на `http://10.10.11.139:8000`.
Перезапуск после доставки кода:

```
ssh zaurus 'pct exec 169 -- sh -lc "cd /opt/omra.fitness/server && docker compose up -d --build"'
```

## Текущее состояние проекта — 2026-09-16

- Этапы 0–2 из `ROADMAP.md` завершены: tenant boundary, `Assignment`/`Submission`,
  программы, уроки и enrollment работают end-to-end.
- Реализация этапа 3 завершена в коде: Fitness принимает подписанный `message.in`,
  копирует video attachment из `omra.crm`, дедуплицирует событие, создаёт попытку,
  запускает pose pipeline и доставляет исходящие сообщения через persistent outbox.
- Ядро этапа 4 реализовано: `/` — публичный Jinja/Tailwind-лендинг, кабинет тренера
  перенесён на `/app`, форма пилота создаёт lead/deal через company-scoped
  `CRM_PILOT_API_KEY`, доступны metadata, canonical, `robots.txt` и sitemap.
- Актуальная миграция Fitness: `f8c1a4b6d902`; локальная Postgres на head.
- Последняя проверка Fitness: 29 tests passed. Browser smoke проверил landing на
  1440×1000 и 390×844 без horizontal overflow, кабинет и video detail под `/app`;
  cross-service submit создал корректно атрибутированные lead/deal в `omra.crm`.
- Незакрытый gate этапа 3: реальный Telegram round trip. В локальном `omra.crm` нет
  рабочего Telegram agent/session; тестовые `telegram_user` agents имеют пустой config
  и невалидные session keys. До production-публикации заменить схематичный блок лендинга
  реальными desktop/mobile материалами после provider smoke.
- Задачи следующей сессии ведутся в `ROADMAP.md` → «Бэклог на завтра».

## Общие правила проекта (см. также `~/.claude/CLAUDE.md`)

- Docker → всегда лог-ротация `json-file` (уже настроено per-service в
  `server/docker-compose.yml`).
- Секреты в `.env` не теряются при пересборке/деплое — `env_file` в compose,
  никогда не хардкодить в `Dockerfile`/коде.
