---
title: "08. ConfigMap и Secret"
description: "ConfigMap и Secret: env/envFrom/том, base64 не шифрование, приватный реестр, SOPS/ESO — конспект и задачи"
---

# 08. ConfigMap и Secret

> Роадмап → 6. Kubernetes → Основные сущности → **ConfigMap**, **Secret**.
> Практика роадмапа: «Написать манифесты руками: Deployment + Service + **ConfigMap**».
> **После темы ты умеешь:** выносить конфигурацию из образа, понимать разницу между
> env и томом и объяснять, почему Secret — это не шифрование.

---

## 🗺️ Карта темы

```text:no-line-numbers
                        ┌──────────── ConfigMap ────────────┐
                        │ обычный конфиг: URL, флаги, файлы │
                        └───────────────┬───────────────────┘
                                        │
               ┌────────────────────────┴────────────────────────┐
               ▼                                                 ▼
      ПОДКЛЮЧИТЬ КАК ENV                            ПОДКЛЮЧИТЬ КАК ТОМ (файлы)
      env / envFrom                                  volumes + volumeMounts
      ────────────────────                           ────────────────────────
      • читается ОДИН раз при старте                 • обновляется автоматически (~1 мин)
      • изменение → нужен рестарт пода               • но приложение должно перечитать файл
      • удобно для простых значений                  • удобно для nginx.conf, application.yml

                        ┌──────────── Secret ───────────────┐
                        │ пароли, токены, ключи, TLS        │
                        │ base64 ≠ шифрование!              │
                        └───────────────────────────────────┘
```

---

## 1. ConfigMap

### Создание

```bash
# из литералов
kubectl create configmap app-config \
  --from-literal=LOG_LEVEL=debug \
  --from-literal=DB_HOST=postgres

# из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap nginx-config --from-file=nginx.conf

# из каталога (каждый файл — отдельный ключ)
kubectl create configmap configs --from-file=./conf.d/

# из env-файла (каждая строка KEY=VALUE — отдельный ключ)
kubectl create configmap app-env --from-env-file=.env

# каркас манифеста
kubectl create configmap app-config --from-literal=A=1 --dry-run=client -o yaml
```

### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  LOG_LEVEL: "debug"                    # простые ключи
  DB_HOST: "postgres"
  MAX_CONNECTIONS: "100"                # ⚠️ всё — строки, число в кавычках
  application.yml: |                    # целый файл как значение
    server:
      port: 8080
    logging:
      level: DEBUG
  nginx.conf: |
    server {
      listen 80;
      location / { proxy_pass http://backend:8080; }
    }
immutable: false                         # true → нельзя менять, зато меньше нагрузка на API
```

### Подключение: три способа ⭐

```yaml
spec:
  containers:
    - name: app
      image: myapp:1.0

      # 1) отдельные переменные
      env:
        - name: LOG_LEVEL
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: LOG_LEVEL
              optional: true            # не падать, если ключа нет

      # 2) ВСЕ ключи как переменные окружения
      envFrom:
        - configMapRef:
            name: app-config
            prefix: APP_               # необязательно: APP_LOG_LEVEL и т.д.

      # 3) как файлы
      volumeMounts:
        - name: config
          mountPath: /etc/nginx/conf.d
          readOnly: true
  volumes:
    - name: config
      configMap:
        name: nginx-config
        items:                          # выборочно, с переименованием
          - key: nginx.conf
            path: default.conf
        defaultMode: 0644
```

| Способ | Обновляется без рестарта? | Когда применять |
|--------|---------------------------|-----------------|
| `env` / `configMapKeyRef` | ❌ нет | простые значения, 12-factor-приложения |
| `envFrom` | ❌ нет | много переменных разом |
| Том (volume) | ✅ да, примерно за минуту | конфигурационные файлы (nginx, java, prometheus) |

> ⚠️ Даже при монтировании томом файл обновится, но **приложение должно само перечитать
> его**. nginx перечитает по `nginx -s reload`, Prometheus умеет watch, большинство
> приложений — нет. Поэтому в реальности почти всегда делают рестарт.

### ⭐ Приём: рестарт при изменении конфига

```yaml
# в шаблоне пода
metadata:
  annotations:
    checksum/config: "{{ include (print $.Template.BasePath \"/configmap.yaml\") . | sha256sum }}"
```
Это Helm-приём (тема 15): меняется ConfigMap → меняется аннотация → меняется шаблон пода →
Deployment катит новую ревизию. Без Helm тот же эффект даёт `kubectl rollout restart`.

---

## 2. Secret

### Чем отличается от ConfigMap

| | ConfigMap | Secret |
|---|---|---|
| Назначение | обычная конфигурация | пароли, токены, ключи, сертификаты |
| Хранение значений | как есть | **base64** (это кодирование, не шифрование) |
| В etcd | открытым текстом | открытым текстом, **если не включён encryption at rest** |
| RBAC | обычно читаем всем | ограничивают отдельно |
| В `kubectl describe` | значения видны | значения скрыты (`<redacted>`) |
| Монтирование | файл на диске ноды | по возможности в `tmpfs` (память) |

> 🎤 **Вопрос собеса:** «Secret безопасен?» Правильный ответ: «Сам по себе нет —
> это base64, а не шифрование. Безопасность даёт: включённый encryption at rest в etcd,
> строгий RBAC на чтение секретов, отказ от хранения секретов в git (или SOPS/sealed-secrets),
> внешние хранилища вроде Vault через External Secrets Operator».

### Типы Secret

| Тип | Назначение |
|-----|------------|
| `Opaque` | произвольные данные (по умолчанию) |
| `kubernetes.io/dockerconfigjson` | доступ к приватному реестру (`imagePullSecrets`) |
| `kubernetes.io/tls` | сертификат и ключ для Ingress |
| `kubernetes.io/service-account-token` | токен ServiceAccount |
| `kubernetes.io/basic-auth`, `ssh-auth` | логин-пароль, SSH-ключ |

### Создание

```bash
kubectl create secret generic db-secret \
  --from-literal=username=app \
  --from-literal=password='S3cr3t!'

kubectl create secret docker-registry regcred \
  --docker-server=registry.gitlab.com \
  --docker-username=$CI_REGISTRY_USER \
  --docker-password=$CI_REGISTRY_PASSWORD

kubectl create secret tls web-tls --cert=tls.crt --key=tls.key
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-secret
type: Opaque
stringData:                  # ⭐ пишем как есть, кубер закодирует сам
  username: app
  password: "S3cr3t!"
# data:                      # либо так — вручную закодированное base64
#   username: YXBw
```

Посмотреть значение:
```bash
kubectl get secret db-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

### Подключение

```yaml
spec:
  imagePullSecrets:
    - name: regcred                       # для приватного реестра
  containers:
    - name: app
      env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef: { name: db-secret, key: password }
      envFrom:
        - secretRef: { name: db-secret }
      volumeMounts:
        - name: tls
          mountPath: /etc/tls
          readOnly: true
  volumes:
    - name: tls
      secret:
        secretName: web-tls
        defaultMode: 0400
```

> ⚠️ Секрет, отданный через `env`, виден в `kubectl describe pod` любому,
> у кого есть доступ к подам, и часто утекает в логи приложения и трейсы ошибок.
> Монтирование файлом безопаснее.

---

## 3. Секреты и git — как делают в реальности

| Подход | Суть | Плюсы / минусы |
|--------|------|----------------|
| Секреты в CI-переменных | Пайплайн создаёт Secret при деплое | Просто; секрет размазан по настройкам CI |
| **SOPS** (+ age/KMS) | Зашифрованный YAML лежит в git | ⭐ Git как источник правды, нужен ключ расшифровки |
| **Sealed Secrets** | Контроллер расшифровывает в кластере | Удобно с GitOps, привязка к кластеру |
| **External Secrets Operator** | Секреты в Vault/AWS SM/GCP SM, оператор синхронизирует | ⭐ Промышленный вариант, ротация и аудит |
| Vault Agent Injector | Sidecar подкладывает секрет в под | Гибко, но сложнее |

**Правило, которое не обсуждается:** открытый секрет не попадает в git никогда.
Вариант «оно же в приватном репозитории» — не аргумент.

---

## 4. Практический пример: Deployment + ConfigMap + Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  LOG_LEVEL: "info"
  DB_HOST: "postgres"
  DB_PORT: "5432"
  app.properties: |
    feature.newUI=true
    cache.ttl=300
---
apiVersion: v1
kind: Secret
metadata:
  name: db-secret
type: Opaque
stringData:
  DB_USER: app
  DB_PASSWORD: "change-me"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  replicas: 2
  selector:
    matchLabels: { app: app }
  template:
    metadata:
      labels: { app: app }
      annotations:
        checksum/config: "v1"        # менять руками или генерировать в CI/Helm
    spec:
      containers:
        - name: app
          image: myapp:1.0
          envFrom:
            - configMapRef: { name: app-config }
            - secretRef: { name: db-secret }
          volumeMounts:
            - name: props
              mountPath: /etc/app
              readOnly: true
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits:   { cpu: 500m, memory: 256Mi }
      volumes:
        - name: props
          configMap:
            name: app-config
            items:
              - key: app.properties
                path: app.properties
```

---

## 5. Грабли

| Грабля | Симптом | Лечение |
|--------|---------|---------|
| ConfigMap/Secret не существует | Под в `CreateContainerConfigError` | Создать, либо `optional: true` |
| Изменили ConfigMap, ждём эффекта | Приложение работает по-старому | `rollout restart` или checksum-аннотация |
| Числа и `true` без кавычек | Ошибка типа при apply | Все значения `data` — строки |
| Монтирование в непустой каталог | Файлы образа «исчезли» | Монтировать `subPath` или отдельный каталог |
| `subPath` | Файл **не обновляется** при изменении ConfigMap | Осознанный компромисс: либо обновление, либо subPath |
| Секрет в `env` | Утёк в логи и в `describe` | Монтировать файлом |
| Секрет в git открытым текстом | Компрометация | SOPS / Sealed Secrets / ESO |
| ConfigMap больше 1 МБ | Ошибка при создании | Лимит etcd; выносить в том/образ |
| Забыли `imagePullSecrets` | `ImagePullBackOff` на приватном образе | Добавить секрет реестра (или в ServiceAccount) |
| Namespace | Под не видит секрет из другого namespace | ConfigMap/Secret — объекты namespace, копировать |

---

## 💼 Как это в DevOps

- Конфигурация из образа выносится всегда: один образ — много окружений.
  Это ровно принцип 12-factor из блока Docker.
- Типичная схема: общие значения в `values.yaml` чарта → ConfigMap; секреты — из Vault
  или CI-переменных → Secret; ничего чувствительного в git.
- Приватный реестр из блока CI/CD подключается через `imagePullSecrets`
  (лучше — прописанный в ServiceAccount, тогда его не надо указывать в каждом поде).
- Checksum-аннотация на ConfigMap — стандартная строка в любом промышленном чарте.
- Ротация секретов — отдельная задача: смена значения в Secret сама по себе
  не перезапускает поды.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать ConfigMap из литералов | `kubectl create cm app --from-literal=K=V` |
| Создать из файла | `kubectl create cm nginx --from-file=nginx.conf` |
| Создать Secret | `kubectl create secret generic db --from-literal=password=xxx` |
| Секрет для реестра | `kubectl create secret docker-registry regcred ...` |
| TLS-секрет | `kubectl create secret tls web-tls --cert=... --key=...` |
| Прочитать значение секрета | `kubectl get secret db -o jsonpath='{.data.password}' \| base64 -d` |
| Все ключи как env | `envFrom: [{configMapRef: {name: app}}]` |
| Один ключ как env | `valueFrom.configMapKeyRef` |
| Подключить файлом | `volumes.configMap` + `volumeMounts` |
| Обновить конфиг в подах | `kubectl rollout restart deploy/app` |
| Запретить изменения | `immutable: true` |

---

## 🧠 Что запомнить

1. ConfigMap — обычная конфигурация, Secret — чувствительные данные; API почти одинаков.
2. Значения `data` — всегда **строки**; числа и булевы значения в кавычках.
3. Три способа подключения: `env`, `envFrom`, том. Первые два требуют рестарта пода.
4. Том с ConfigMap обновляется автоматически (порядка минуты), но приложение должно
   перечитать файл; при `subPath` обновления не будет вовсе.
5. ⭐ Secret — это **base64**, а не шифрование; нужны encryption at rest и RBAC.
6. Секреты в git — только зашифрованные (SOPS, Sealed Secrets) либо через ESO/Vault.
7. Секрет в переменной окружения легко утекает в логи — файл надёжнее.
8. Отсутствующий ConfigMap/Secret даёт `CreateContainerConfigError`.
9. ConfigMap и Secret живут в namespace и не видны из других namespace.
10. Ограничение размера — около 1 МБ (лимит etcd).
11. `imagePullSecrets` — доступ к приватному реестру; удобно вешать на ServiceAccount.
12. Изменение ConfigMap само по себе не перезапускает поды: нужен `rollout restart`
    или checksum-аннотация.

---

## Задачи

> Главный практический навык темы: вынести конфиг из образа и понимать,
> что произойдёт с подами при изменении конфигурации.

---

### Блок A. Теория

**A1.** Зачем нужен ConfigMap, если можно положить конфиг в образ?

<details><summary>Ответ</summary>

Чтобы один и тот же образ работал в разных окружениях: конфигурация
подставляется снаружи, образ остаётся неизменным (принцип 12-factor).

</details>

**A2.** ⭐ Назови три способа подключить ConfigMap к поду.

<details><summary>Ответ</summary>

Отдельные переменные через `env.valueFrom.configMapKeyRef`; все ключи через
`envFrom.configMapRef`; файлы через том `volumes.configMap`.

</details>

**A3.** Какой из способов обновляется без рестарта пода?

<details><summary>Ответ</summary>

Только том: файлы обновляются автоматически (обычно в пределах минуты).
Переменные окружения фиксируются при старте процесса.

</details>

**A4.** Почему даже при монтировании томом приложение может не увидеть новый конфиг?

<details><summary>Ответ</summary>

Потому что перечитывание файла — обязанность приложения. Если оно читает
конфиг один раз при старте, новый файл никак не повлияет.

</details>

**A5.** ⭐ Что нужно сделать, чтобы поды подхватили изменённый ConfigMap?

<details><summary>Ответ</summary>

`kubectl rollout restart deploy/app`, либо изменить шаблон пода
(например, checksum-аннотацию), чтобы Deployment сам сделал выкатку.

</details>

**A6.** Почему значения в `data` пишут в кавычках?

<details><summary>Ответ</summary>

Значения `data` должны быть строками: без кавычек `100` или `true`
интерпретируются YAML'ом как число и булево значение, и apply завершится ошибкой типа.

</details>

**A7.** Что делает `optional: true` у `configMapKeyRef`?

<details><summary>Ответ</summary>

Разрешает поду стартовать, даже если ключа или объекта нет; переменная
просто не будет установлена.

</details>

**A8.** Что делает `envFrom` и чем отличается от `env`?

<details><summary>Ответ</summary>

`envFrom` подключает все ключи объекта как переменные окружения (можно
с префиксом); `env` — конкретные ключи с явными именами.

</details>

**A9.** Что такое `immutable: true` и зачем это нужно?

<details><summary>Ответ</summary>

Запрещает изменять содержимое объекта. Снижает нагрузку на API server
и kubelet (не нужно следить за изменениями) и защищает от случайных правок.

</details>

**A10.** Какой максимальный размер у ConfigMap и почему?

<details><summary>Ответ</summary>

Около 1 МБ — ограничение на размер объекта в etcd.

</details>

**A11.** ⭐ Чем Secret отличается от ConfigMap?

<details><summary>Ответ</summary>

Назначением и обращением: Secret предназначен для чувствительных данных,
хранится в base64, скрывается в выводе `describe`, монтируется в память,
и на него обычно вешают отдельные права RBAC.

</details>

**A12.** ⭐ Secret зашифрован? Ответь как на собесе.

<details><summary>Ответ</summary>

Нет. base64 — это кодирование. Защиту дают encryption at rest в etcd,
RBAC, отказ от хранения открытых секретов в git и внешние хранилища (Vault,
облачные менеджеры секретов) через ESO.

</details>

**A13.** Что такое encryption at rest и зачем он нужен?

<details><summary>Ответ</summary>

Шифрование данных в etcd на уровне API server (EncryptionConfiguration):
секреты хранятся на диске в зашифрованном виде. Иначе доступ к диску/бэкапу etcd
означает доступ ко всем секретам.

</details>

**A14.** Назови четыре типа Secret и их назначение.

<details><summary>Ответ</summary>

`Opaque` — произвольные данные; `kubernetes.io/dockerconfigjson` — доступ
к реестру; `kubernetes.io/tls` — сертификат и ключ; `kubernetes.io/service-account-token`
— токен SA (плюс `basic-auth`, `ssh-auth`).

</details>

**A15.** Чем `stringData` отличается от `data`?

<details><summary>Ответ</summary>

В `stringData` значения пишутся открытым текстом и кодируются кубером
при сохранении; в `data` нужно класть уже закодированное base64.

</details>

**A16.** Как посмотреть реальное значение секрета?

<details><summary>Ответ</summary>

`kubectl get secret NAME -o jsonpath='{.data.KEY}' | base64 -d`.

</details>

**A17.** Почему секрет в переменной окружения хуже, чем в файле?

<details><summary>Ответ</summary>

Переменные окружения видны в `describe`/спеке пода, попадают в дампы
ошибок, логи старта, трейсы и дочерние процессы; файл проще ограничить правами
и не печатать случайно.

</details>

**A18.** Как подключить приватный реестр образов? Где удобнее указать секрет?

<details><summary>Ответ</summary>

Создать `docker-registry`-секрет и указать его в `imagePullSecrets` пода —
или, удобнее, прописать в ServiceAccount, тогда он применится ко всем подам
этого SA в namespace.

</details>

**A19.** Назови три способа хранить секреты при GitOps.

<details><summary>Ответ</summary>

SOPS с ключом age/KMS; Sealed Secrets; External Secrets Operator
поверх Vault или облачного менеджера секретов.

</details>

**A20.** Что произойдёт с подом, если указанный ConfigMap не существует?

<details><summary>Ответ</summary>

Под не стартует: статус `CreateContainerConfigError`, в событиях —
`configmap "..." not found`.

</details>

**A21.** Виден ли ConfigMap из соседнего namespace?

<details><summary>Ответ</summary>

Нет: это объекты уровня namespace. Нужна копия в каждом namespace
(либо оператор, который их синхронизирует).

</details>

**A22.** Что произойдёт, если смонтировать ConfigMap в каталог, где уже есть файлы образа?

<details><summary>Ответ</summary>

Каталог будет заменён содержимым ConfigMap: файлы образа станут недоступны.
Нужно монтировать в отдельный каталог или использовать `subPath`.

</details>

**A23.** Что такое `subPath` и какой у него побочный эффект?

<details><summary>Ответ</summary>

Монтирование одного файла (или подкаталога) вместо всего тома.
Побочный эффект: такой файл **не обновляется** при изменении ConfigMap.

</details>

**A24.** Что делает `defaultMode` у тома с секретом?

<details><summary>Ответ</summary>

Задаёт права доступа для создаваемых файлов (например, `0400` — чтение
только владельцу).

</details>

**A25.** Перезапустятся ли поды после ротации пароля в Secret?

<details><summary>Ответ</summary>

Нет. Если секрет подключён через `env` — значение останется старым
до рестарта; при монтировании томом файл обновится, но приложение должно его перечитать.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
data:
  MAX_CONN: 100
```
Вопрос: применится ли такой ConfigMap?

<details><summary>Ответ</summary>

Нет: `100` без кавычек — число, а `data` принимает только строки;
будет ошибка валидации.

</details>

**B2.**
```yaml
env:
  - name: LOG_LEVEL
    valueFrom:
      configMapKeyRef: { name: app-config, key: LOG_LEVEL }
# ConfigMap изменили, LOG_LEVEL стал debug
```
Вопрос: увидит ли работающий под новое значение?

<details><summary>Ответ</summary>

Нет: переменные окружения фиксируются при запуске процесса.
Нужен рестарт пода.

</details>

**B3.**
```yaml
volumeMounts:
  - name: config
    mountPath: /etc/nginx/conf.d
# ConfigMap изменили
```
Вопрос: изменится ли файл в контейнере? Изменится ли поведение nginx?

<details><summary>Ответ</summary>

Файл в контейнере обновится (примерно через минуту), но nginx
продолжит работать со старой конфигурацией, пока не выполнит reload.

</details>

**B4.**
```yaml
volumeMounts:
  - name: config
    mountPath: /etc/app/app.conf
    subPath: app.conf
# ConfigMap изменили
```
Вопрос: обновится ли файл?

<details><summary>Ответ</summary>

Нет: при `subPath` том не отслеживает изменения.

</details>

**B5.**
```yaml
envFrom:
  - configMapRef: { name: missing-config }
```
Вопрос: в каком статусе окажется под и что скажет `describe`?

<details><summary>Ответ</summary>

Под не стартует, статус `CreateContainerConfigError`,
в событиях — `configmap "missing-config" not found`.

</details>

**B6.**
```bash
kubectl get secret db-secret -o yaml
# data:
#   password: UzNjcjN0IQ==
```
Вопрос: это шифрование? Что можно сделать с этой строкой?

<details><summary>Ответ</summary>

Это base64. Любой, кто получил строку, декодирует её одной командой:
`echo UzNjcjN0IQ== | base64 -d`.

</details>

**B7.**
```yaml
kind: Secret
stringData:
  password: "123"
data:
  password: "MTIz"
```
Вопрос: что окажется в итоговом секрете?

<details><summary>Ответ</summary>

Значение из `stringData` имеет приоритет: в итоговом секрете будет `123`
(оно перезапишет одноимённый ключ из `data`).

</details>

**B8.**
```bash
kubectl describe pod app | grep -A5 Environment
#   DB_PASSWORD:  <set to the key 'password' in secret 'db-secret'>
```
Вопрос: видно ли значение? А в `kubectl get pod -o yaml`?

<details><summary>Ответ</summary>

В `describe` значение скрыто. В `get pod -o yaml` виден только источник
(ссылка на секрет), но сам секрет доступен тому, у кого есть права на его чтение.

</details>

**B9.**
```yaml
volumes:
  - name: config
    configMap:
      name: app-config
      items:
        - key: app.yml
          path: application.yml
```
Вопрос: какие файлы появятся в каталоге монтирования?

<details><summary>Ответ</summary>

Только один файл `application.yml` — при использовании `items`
монтируются исключительно перечисленные ключи.

</details>

---

### Блок C. Практика

#### C1. 🔑 ConfigMap тремя способами
Создай ConfigMap с тремя ключами и одним файлом. Подключи к одному поду:
1. один ключ через `env`;
2. все ключи через `envFrom` с префиксом;
3. файл через том.
Зайди в под и проверь всё три способа (`env`, `cat`).

#### C2. 🔑 Обновление конфига
1. Подключи ConfigMap и как env, и как том.
2. Измени значение в ConfigMap (`kubectl edit cm` или `apply`).
3. Каждые 15 секунд проверяй внутри пода: `env | grep LOG` и `cat /etc/app/...`.
4. Засеки, через сколько обновился файл, и убедись, что переменная не изменилась.
5. Сделай `rollout restart` и проверь снова.

<details><summary>Ответ</summary>

Файл обновляется примерно за минуту (зависит от периода синхронизации kubelet);
переменная окружения не меняется никогда без рестарта.

</details>

#### C3. subPath
Смонтируй один ключ через `subPath` в существующий каталог.
Измени ConfigMap и убедись, что файл **не** обновился. Запиши вывод.

#### C4. Монтирование поверх каталога
Смонтируй ConfigMap в `/etc/nginx/conf.d` контейнера nginx и посмотри,
что произошло с исходными файлами каталога. Сформулируй правило.

<details><summary>Ответ</summary>

Правило: монтирование тома **замещает** содержимое каталога.
Либо отдельный каталог, либо `subPath` для конкретного файла.

</details>

#### C5. 🔑 nginx с конфигом из ConfigMap
Собери рабочую связку: ConfigMap с `default.conf` (проксирование на бэкенд),
Deployment с nginx, том. Проверь, что конфигурация применилась (`nginx -T` внутри пода).

#### C6. Отсутствующий ConfigMap
Сошлись на несуществующий ConfigMap и посмотри статус пода и события.
Потом добавь `optional: true` и сравни поведение.

<details><summary>Ответ</summary>

Без `optional` — `CreateContainerConfigError`; с `optional: true`
под запускается, переменная просто отсутствует.

</details>

#### C7. 🔑 Secret
1. Создай Secret с паролем.
2. Подключи его через `env` и через том.
3. Прочитай значение обоими способами внутри пода.
4. Посмотри `kubectl describe pod` — видно ли значение?
5. Посмотри `kubectl get secret -o yaml` и раскодируй base64.

#### C8. Права на файл секрета
Смонтируй секрет с `defaultMode: 0400` и проверь `ls -l` внутри пода.
Объясни, зачем ограничивать права.

#### C9. Приватный реестр
1. Создай `docker-registry`-секрет (можно с фиктивными данными).
2. Подключи через `imagePullSecrets` в поде.
3. Подключи его же к ServiceAccount `default` и убедись, что в поде указывать
   его больше не нужно.

#### C10. TLS-секрет
Сгенерируй самоподписанный сертификат и создай `kubernetes.io/tls`-секрет.
Он понадобится в теме 12 для Ingress.
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt -subj "/CN=demo.local"
kubectl create secret tls web-tls --cert=tls.crt --key=tls.key
```

#### C11. checksum-аннотация вручную
1. Посчитай хеш ConfigMap: `kubectl get cm app-config -o yaml | sha256sum`.
2. Пропиши его в аннотацию шаблона пода.
3. Измени ConfigMap, пересчитай хеш, обнови аннотацию, примени.
4. Убедись, что Deployment начал выкатку. Это ручная версия Helm-приёма из темы 15.

#### C12. immutable
Сделай ConfigMap с `immutable: true`, попробуй его изменить. Запиши ошибку.
Придумай, как обновлять такой конфиг (подсказка: новое имя + смена ссылки в Deployment).

<details><summary>Ответ</summary>

Ошибка вида `field is immutable`. Обновление делают через новый объект
(`app-config-v2`) и правку ссылки в Deployment — заодно это автоматически
вызывает выкатку.

</details>

#### C13. Секреты и git (со звёздочкой)
Зашифруй Secret с помощью SOPS (или хотя бы разберись, как это работает)
и опиши в заметке, как выглядит процесс: где ключ, кто расшифровывает, что лежит в git.

#### C14. Утечка секрета (со звёздочкой)
Сделай приложение, которое печатает все переменные окружения при старте
(`env`). Убедись, что секрет виден в `kubectl logs`. Сформулируй, почему
монтирование файлом безопаснее.

---

### Блок D. Инциденты

**D1.** Поменяли ConfigMap, сделали apply — приложение работает по-старому.
Три причины и решение.

<details><summary>Ответ</summary>

Конфиг подключён через `env` (нужен рестарт); приложение читает файл
только при старте; изменение внесено в другой namespace/кластер или в другой объект.
Решение — `rollout restart` и checksum-аннотация.

</details>

**D2.** Под в `CreateContainerConfigError`. Алгоритм разбора.

<details><summary>Ответ</summary>

`kubectl describe pod` → событие об отсутствующем ConfigMap/Secret или
отсутствующем ключе; проверить namespace, имя, наличие ключа, права ServiceAccount.

</details>

**D3.** После монтирования ConfigMap в `/etc/nginx` nginx перестал запускаться.
Что произошло?

<details><summary>Ответ</summary>

Том перекрыл каталог с конфигурацией образа, и nginx лишился основных файлов.
Монтировать в `conf.d` отдельным каталогом или использовать `subPath`.

</details>

**D4.** Секрет с паролем БД оказался в публичном репозитории. Порядок действий.

<details><summary>Ответ</summary>

Считать секрет скомпрометированным: немедленно ротировать пароль/токен
в источнике, обновить Secret в кластерах, проверить логи доступа,
удалить историю из репозитория (и помнить, что она могла быть склонирована),
затем внедрить SOPS/ESO, чтобы это не повторилось.

</details>

**D5.** В логах приложения при ошибке печатаются все переменные окружения,
включая пароль. Что менять в архитектуре конфигурации?

<details><summary>Ответ</summary>

Передавать секреты файлом, а не через окружение; в приложении убрать
печать окружения; при необходимости маскировать значения в логах.

</details>

**D6.** Под не может скачать образ из приватного реестра, хотя секрет создан.
Что проверить (три пункта)?

<details><summary>Ответ</summary>

Секрет в том же namespace; правильный тип (`dockerconfigjson`)
и корректный `--docker-server`; секрет указан в `imagePullSecrets` пода
или в ServiceAccount; учётные данные действительно валидны.

</details>

**D7.** ConfigMap с большим JSON (3 МБ) не создаётся. Почему и что делать?

<details><summary>Ответ</summary>

Лимит размера объекта в etcd около 1 МБ. Выносить данные в том,
в образ, в объектное хранилище или разбивать на части.

</details>

**D8.** После ротации пароля в Secret часть подов работает со старым значением,
часть — с новым. Как такое возможно?

<details><summary>Ответ</summary>

Поды, подключившие секрет через `env`, держат старое значение до рестарта;
поды с томом получили новое. Ротация всегда требует перезапуска потребителей.

</details>

**D9.** Приложение в namespace `prod` не видит ConfigMap, который «точно есть».
Что проверить первым делом?

<details><summary>Ответ</summary>

Namespace объекта и namespace пода, точное имя, опечатки, а также
права ServiceAccount на чтение.

</details>

**D10.** Разработчик просит «просто положить .env в образ». Какие аргументы приведёшь?

<details><summary>Ответ</summary>

Один образ должен работать во всех окружениях; конфиг в образе означает
пересборку под каждое окружение и риск утечки секретов в слои образа.
Конфигурация — снаружи, через ConfigMap/Secret.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое ConfigMap и Secret, чем отличаются?

<details><summary>Ответ</summary>

ConfigMap — обычная конфигурация, Secret — чувствительные данные (base64,
скрыт в выводе, отдельный RBAC, монтируется в память).

</details>

**2.** Как подключить конфигурацию к поду? Назови все способы.

<details><summary>Ответ</summary>

Через `env.valueFrom`, через `envFrom`, через том с файлами.

</details>

**3.** Обновится ли конфиг в работающем поде?

<details><summary>Ответ</summary>

Переменные окружения — нет; файлы из тома — да (кроме `subPath`),
но приложение должно их перечитать.

</details>

**4.** Secret зашифрован? Как сделать хранение безопасным?

<details><summary>Ответ</summary>

Нет, это кодирование. Нужны encryption at rest, RBAC, внешние хранилища
и отказ от открытых секретов в git.

</details>

**5.** Как хранить секреты при GitOps?

<details><summary>Ответ</summary>

SOPS, Sealed Secrets, External Secrets Operator поверх Vault/облачного менеджера.

</details>

**6.** Как подключить приватный реестр?

<details><summary>Ответ</summary>

Секретом типа `docker-registry`, указанным в `imagePullSecrets`
или привязанным к ServiceAccount.

</details>

**7.** Почему секреты лучше монтировать файлом, а не через env?

<details><summary>Ответ</summary>

Переменные окружения легко утекают в логи, дампы и вывод `describe`;
файл можно ограничить правами и не выводить наружу.

</details>

**8.** Что произойдёт, если ConfigMap не существует?

<details><summary>Ответ</summary>

Под не запустится: `CreateContainerConfigError` (если не указан `optional: true`).

</details>

**9.** Как заставить поды перечитать новую конфигурацию?

<details><summary>Ответ</summary>

`rollout restart` или изменение шаблона пода (checksum-аннотация).

</details>

**10.** Какие ограничения есть у ConfigMap?

<details><summary>Ответ</summary>

Размер около 1 МБ, значения только строковые, область видимости — namespace,
отсутствие встроенного версионирования.

</details>

---

### 🎯 Чек-лист

- [ ] Подключал ConfigMap всеми тремя способами
- [ ] Проверил на практике, что env не обновляется, а файл обновляется
- [ ] Знаю про `subPath` и его побочный эффект
- [ ] Умею заставить поды перечитать конфиг (`rollout restart`, checksum)
- [ ] ⭐ Отвечаю на «Secret зашифрован?» правильно и полно
- [ ] Создавал `docker-registry` и `tls` секреты
- [ ] Понимаю, почему секрет в env хуже, чем файлом
- [ ] Знаю три способа хранить секреты при GitOps
- [ ] Ловил `CreateContainerConfigError` и умею его разбирать
