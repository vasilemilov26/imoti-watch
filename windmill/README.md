# Пускане през Windmill (вместо GitHub Actions)

Windmill на вашия сървър пуска скенера по график. Кодът и данните остават в GitHub хранилището,
а таблото си остава на GitHub Pages. На сървъра не се инсталира нищо.

## 1. GitHub token
1. https://github.com/settings/personal-access-tokens/new
2. Token name: `windmill-imoti` · Expiration: 1 година
3. Repository access: **Only select repositories** → `imoti-watch`
4. Permissions → Repository permissions → **Contents: Read and write**
5. Generate token → копирайте го (започва с `github_pat_`).

## 2. Секретни променливи в Windmill
*Variables → + Variable* (отметнете **Secret**):
- `github_token` – токенът от стъпка 1
- `smtp_pass` – Gmail App password
- (по избор) `anthropic_api_key`

## 3. Скриптовете
*+ Script → Python* → изтрийте примерния код → поставете съдържанието на `imoti_scan.py` → Save
(път напр. `f/imoti/scan`). Същото за `imoti_digest.py` (`f/imoti/digest`).

## 4. Графици
В скрипта → **Schedules → New schedule**:
- **scan**: cron `0 17 */4 * * *` (на всеки 4 часа), timezone Europe/Sofia.
  Аргументи: `github_repo` = `ВАШЕТО-ИМЕ/imoti-watch`, `github_token` → бутон *Variable* → `github_token`,
  `max_minutes` = 40.
- **digest**: cron `0 40 7 * * *`, timezone Europe/Sofia. Аргументи: repo, token, `smtp_user`,
  `smtp_pass` (Variable), `mail_to`.

(Windmill използва 6 полета в cron – първото са секундите.)

## 5. Спрете GitHub Actions
В GitHub → **Actions** → „Сканиране на търгове“ → `···` → **Disable workflow**. Същото за „Сутрешен имейл“.
Иначе двете ще сканират едновременно.

## Ако Windmill спре скрипта по време
Някои инсталации ограничават една задача до 15 мин. Тогава сложете `max_minutes` = 12 и графика
на всеки час (`0 17 * * * *`). Скенерът продължава от там, докъдето е стигнал.
