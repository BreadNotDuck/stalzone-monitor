# stalzone-monitor

Мониторинг дешёвых лотов на аукционе **STALZONE** с уведомлениями в **Telegram**.

## Критерий «дешёвого» лота

Уведомление приходит, если лот **минимум на 10%** (настраивается) дешевле **хотя бы одного** из:

1. **Средней цены** последних продаж на аукционе
2. **Следующего по стоимости лота** (ближайший более дорогой лот того же предмета)

---

## Пошаговая инструкция

### Шаг 1. Установить Python

1. Скачайте Python 3.11+ с [python.org](https://www.python.org/downloads/)
2. При установке поставьте галочку **«Add Python to PATH»**
3. Проверьте в терминале:

```powershell
python --version
```

### Шаг 2. Получить доступ к STALZONE API

1. Откройте [страницу регистрации API](https://eapi.stalzone.com/registration.html)
2. Перейдите в Telegram-бот регистрации (ссылка на странице)
3. Авторизуйтесь через EXBO-аккаунт
4. Отправьте боту команду `/newapp`
5. Заполните описание приложения (например: «Мониторинг дешёвых лотов на аукционе»)
6. Дождитесь одобрения — бот пришлёт **Client-Id** и **Client-Secret**

> Для тестов можно использовать Demo API: в `config.yaml` укажите `api_base_url: https://dapi.stalzone.com` и demo-токен из [документации](https://eapi.stalzone.com/overview.html#demo-api).

### Шаг 3. Создать Telegram-бота

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`, придумайте имя и username
3. Скопируйте **токен бота** (выглядит как `123456789:ABCdef...`)
4. Напишите своему новому боту любое сообщение (например «привет»)
5. Узнайте свой **chat_id** — откройте в браузере:

```
https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates
```

6. Найдите в ответе `"chat":{"id":123456789}` — это ваш chat_id

### Шаг 4. Настроить проект

```powershell
cd C:\Users\user\stalzone-monitor

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
copy config.yaml.example config.yaml
```

### Шаг 5. Заполнить `.env`

```env
STALZONE_CLIENT_ID=ваш_client_id
STALZONE_CLIENT_SECRET=ваш_client_secret

TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_CHAT_ID=123456789
```

### Шаг 6. Настроить `config.yaml`

По умолчанию уже включено сканирование **всех артефактов**:

```yaml
watch_artifacts: true
scan_batch_size: 80
custom_items: []   # свои предметы добавляются через меню
```

Дополнительные предметы — через меню (`python main.py` → пункт 3), сохраняются в `custom_items`.

### Шаг 7. Запуск

```powershell
python main.py
```

В меню:
- **1** — постоянный мониторинг
- **3** — добавить любой предмет (поиск по названию или id)
- **2** — одна проверка для теста

---

## Пример уведомления

```
🔥 Дешёвый лот на аукционе
АК-74M (y3k2j)
💰 Выкуп: 45 000 ₽
📦 Количество: 1
📊 Средняя цена продаж: 55 000 ₽
⬆️ Следующий лот: 52 000 ₽
📉 Выгода: ~18%
⏳ До конца: 2026-07-12T18:00:00Z
ℹ️ ниже средней цены продаж на 18% (55 000 ₽)
```

---

## Деплой 24/7 (без твоего ПК)

Бот должен крутиться на **VPS/сервере** — дешёвый Linux-сервер (Timeweb, Hetzner, Aeza и т.п.) от ~200–500 ₽/мес.

### Вариант A: Docker (рекомендуется)

На сервере установи [Docker](https://docs.docker.com/engine/install/) и Docker Compose.

```bash
git clone <твой-репозиторий> /opt/stalzone-monitor
cd /opt/stalzone-monitor
cp .env.example .env          # заполни токены
cp config.yaml.example config.yaml
bash deploy/up.sh
```

Команды управления:

```bash
docker compose logs -f      # логи
docker compose restart      # перезапуск
docker compose down         # остановка
docker compose up -d --build  # обновление после git pull
```

Данные (БД, кэш каталога) хранятся в Docker-томе `stalzone-monitor-data`.  
`config.yaml` и `.env` — на диске сервера рядом с проектом.

### Вариант B: systemd (без Docker)

```bash
cd /opt/stalzone-monitor
cp .env.example .env
cp config.yaml.example config.yaml
sudo bash deploy/install-vps.sh
sudo journalctl -u stalzone-monitor -f
```

### Вариант C: GitHub Actions (рекомендуется для «деплой через GitHub»)

Каждый **push в `main`** (или кнопка **Run workflow**) автоматически заливает код на VPS и перезапускает Docker.

#### Один раз

1. Создай **приватный** репозиторий на GitHub и залей проект
2. На VPS (Ubuntu):

```bash
sudo bash deploy/github-bootstrap.sh /opt/stalzone-monitor
```

3. Сгенерируй **отдельную** SSH-пару для деплоя (на ПК):

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\stalzone_deploy -N '""'
```

4. Публичный ключ добавь на VPS в `~/.ssh/authorized_keys` пользователя деплоя
5. В GitHub: **Settings → Secrets and variables → Actions** → New repository secret:

| Secret | Значение |
|--------|----------|
| `VPS_HOST` | IP сервера |
| `VPS_USER` | `root` или другой пользователь |
| `VPS_PORT` | `22` (можно не создавать) |
| `VPS_APP_DIR` | `/opt/stalzone-monitor` |
| `VPS_SSH_KEY` | **приватный** ключ целиком (`stalzone_deploy`) |
| `ENV_FILE` | содержимое `.env` (все строки с токенами) |

6. Первый деплoy: **Actions → Deploy to VPS → Run workflow**

#### Дальше

```bash
git add .
git commit -m "update"
git push
```

GitHub сам задеплоит на VPS.

Агент может: закоммитить изменения → `git push` → деплoy пойдёт автоматически.  
Или вручную: **Actions → Deploy to VPS → Run workflow**.

> `config.yaml` на сервере сохраняется между деплоями, если уже создан.  
> При первом деплое копируется из `config.yaml.example`.

---

### Деплой одной командой с ПК (без GitHub)

1. На VPS один раз: установи Ubuntu, открой SSH (порт 22), добавь свой **публичный** SSH-ключ в `~/.ssh/authorized_keys`
2. Локально:

```powershell
copy deploy\remote.env.example deploy\remote.env
# заполни VPS_HOST, VPS_USER, VPS_APP_DIR, SSH_KEY
.venv\Scripts\python.exe deploy\push.py --check
.venv\Scripts\python.exe deploy\push.py --bootstrap   # первый раз
.venv\Scripts\python.exe deploy\push.py               # каждое обновление
```

После настройки `deploy/remote.env` можно просто написать в чат: **«задеплой на VPS»** — агент запустит `deploy/push.py`.

---

Если `api.telegram.org` недоступен с VPS — добавь в `.env` прокси:

```env
HTTPS_PROXY=http://127.0.0.1:7890
```

---

## Структура проекта

```
stalzone-monitor/
├── main.py
├── config.yaml
├── .env
├── docker-compose.yml   # оркестрация Docker
├── Dockerfile
├── deploy/
│   ├── up.sh            # запуск на Linux
│   ├── up.ps1           # запуск Docker на Windows
│   ├── install-vps.sh   # установка через systemd
│   └── systemd/
└── src/
```

---

- API лимитирует ~200 запросов — не ставьте слишком много предметов с интервалом < 60 сек
- Для сравнения со средней ценой нужно минимум 3 продажи в истории
- Если на аукционе один лот — сравнение идёт только со средней ценой продаж
