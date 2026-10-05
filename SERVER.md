# Частна инсталация на вашия Oracle сървър (без GitHub)

Всичко работи на вашия сървър: сканиране на всеки 4 часа, сутрешен имейл и табло с карта,
защитено с потребител и парола. Нищо не е публично.

## 1. Качете архива на сървъра
**Windows:** с WinSCP (https://winscp.net) се свържете към сървъра със същите данни/ключ, с които
влизате по SSH, и провлачете `imoti-watch.zip` в домашната папка.
**Mac/Linux:** `scp imoti-watch.zip ubuntu@IP-НА-СЪРВЪРА:~`

## 2. Влезте по SSH и пуснете
```bash
sudo apt-get update && sudo apt-get install -y unzip
unzip imoti-watch.zip && cd imoti-watch

# Docker – само ако още го няма (проверка: docker --version)
curl -fsSL https://get.docker.com | sudo sh

cp .env.example .env
nano .env          # попълнете парола за таблото и Telegram токен; Ctrl+O, Enter, Ctrl+X за запис

sudo docker compose up -d --build
sudo docker logs -f imoti-watch      # гледане на лога (Ctrl+C за изход – скенерът продължава)
```

## 3. Отворете порт 8090 (Oracle блокира всичко по подразбиране)
1. **В Oracle Cloud конзолата:** Networking → Virtual Cloud Networks → вашата VCN → Security Lists →
   Default → **Add Ingress Rules**: Source CIDR `0.0.0.0/0` (или само вашия IP), TCP, Destination port `8090`.
2. **На сървъра** (Ubuntu образите на Oracle имат собствена защитна стена):
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8090 -j ACCEPT
   sudo netfilter-persistent save
   ```
3. Отворете `http://IP-НА-СЪРВЪРА:8090` → въведете потребител/парола от `.env`.

Ако вече имате домейн с HTTPS за n8n/Windmill (през Caddy, Nginx или Traefik), по-добре добавете
поддомейн, напр. `imoti.вашдомейн.bg → localhost:8090`, и не отваряйте порт 8090 навън.

## Известия без достъп до вашата поща
- **Telegram (препоръчително):** в Telegram пишете на **@BotFather** → `/newbot` → име → копирайте токена в
  `TELEGRAM_BOT_TOKEN` в `.env`. После пратете едно съобщение на новия бот. Ботът може само да ви пише –
  няма достъп до нищо ваше.
- **Имейл през Brevo** (или друга SMTP услуга) – вижте вариант B в `.env`. Давате само адреса, на който да идва.
- **Нищо** – оставете празно; бюлетинът е в таблото → „Последен бюлетин“.

## Полезни команди
```bash
cd ~/imoti-watch
sudo docker compose restart                 # след промяна в .env
sudo docker compose up -d --build           # след промяна в кода / sources / filters.yaml
sudo docker exec imoti-watch python -m scanner.run --only bcpea   # ръчно сканиране на един източник
sudo docker exec imoti-watch python -m scanner.digest             # ръчно пращане на имейла
```
Данните са в `~/imoti-watch/data/` и се запазват при обновяване.

## Ако досега сте ползвали GitHub
В GitHub → Settings → най-долу **Delete this repository** (или Change visibility → Private).
