#!/usr/bin/env python3
"""Загрузка экспортированных исторических данных в Firebase Firestore + Storage.

Входные данные — JSON из export_to_json.py (export/historical_data.json).
Для каждого сайта:
  - загружает оптимизированные изображения и миниатюры в Storage (если локальные
    файлы существуют) и подменяет относительные пути на публичные URL;
  - создаёт/обновляет документ в коллекции historicalSites с id сайта.

Требуется:
  - установленный пакет:  pip install firebase-admin
  - файл сервисного аккаунта из Firebase Console (project settings → Service accounts);
  - переменные окружения:
      FIREBASE_SERVICE_ACCOUNT_PATH=<путь к serviceAccountKey.json>
      FIREBASE_STORAGE_BUCKET=<например, your-project.appspot.com>

Запуск:
    python3 upload_to_firestore.py                 # реальная загрузка
    python3 upload_to_firestore.py --dry-run       # только показать, что будет загружено

Примечание: для публичных ссылок (blob.make_public()) правила Storage должны
разрешать чтение анонимам. Если это недопустимо — замените на signed URLs.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON_PATH = os.path.join(PROJECT_ROOT, "export", "historical_data.json")

COLLECTION_NAME = "historicalSites"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(
            f"Ошибка: не задана переменная окружения {name}. "
            "Укажите её перед запуском скрипта.",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _resolve_local_file(path: str) -> str | None:
    """Вернуть абсолютный путь к локальному файлу, если он существует."""
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
    return full if os.path.isfile(full) else None


def _upload_blob(bucket, local_path: str, storage_path: str) -> str:
    """Загрузить файл в Storage и вернуть публичный URL."""
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(local_path, content_type="image/jpeg")
    blob.make_public()
    return blob.public_url


def _collect_uploads(site: dict) -> list[tuple[str, str, str]]:
    """Собрать пары (локальный_файл, storage_path, ключ_JSON) для сайта."""
    uploads: list[tuple[str, str, str]] = []
    site_id = site["id"]
    for content in site.get("arContents", []):
        url_file = _resolve_local_file(content.get("url"))
        if url_file:
            uploads.append((url_file, f"sites/{site_id}/{os.path.basename(url_file)}", "url"))
        thumb_file = _resolve_local_file(content.get("thumbnailURL"))
        if thumb_file:
            uploads.append(
                (thumb_file, f"sites/{site_id}/thumbnails/{os.path.basename(thumb_file)}", "thumbnailURL")
            )
    return uploads


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]

    json_path = DEFAULT_JSON_PATH
    if not os.path.isfile(json_path):
        print(f"Ошибка: не найден файл экспорта {json_path}.", file=sys.stderr)
        print("Сначала запустите: python3 export_to_json.py", file=sys.stderr)
        return 1

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    sites = data.get("sites", [])
    if not sites:
        print("В JSON нет сайтов — загружать нечего.")
        return 1

    if dry_run:
        print("DRY-RUN: загрузка не выполняется, показан только план.")
        for site in sites:
            uploads = _collect_uploads(site)
            print(f"  Сайт «{site['name']}» ({site['id']}): {len(uploads)} файлов в Storage")
        print(f"Будет создано/обновлено документов в {COLLECTION_NAME}: {len(sites)}")
        return 0

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
    except ImportError:
        print(
            "Ошибка: пакет firebase-admin не установлен.\n"
            "Установите его в виртуальном окружении проекта:\n"
            "    .venv/bin/pip install firebase-admin",
            file=sys.stderr,
        )
        return 2

    service_account_path = _require_env("FIREBASE_SERVICE_ACCOUNT_PATH")
    storage_bucket = _require_env("FIREBASE_STORAGE_BUCKET")

    if not os.path.isfile(service_account_path):
        print(f"Ошибка: файл сервисного аккаунта не найден: {service_account_path}", file=sys.stderr)
        return 1

    cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred, {"storageBucket": storage_bucket})
    db = firestore.client()
    bucket = storage.bucket()

    uploaded = 0
    for site in sites:
        site_id = site["id"]
        uploads = _collect_uploads(site)

        site = dict(site)
        # arContent оставляем: iOS-модель HistoricalSite требует это поле
        # (FirebaseService декодирует документ через data(as: HistoricalSite.self)),
        # arContents остаётся как дополнительная информация.

        url_map = {}
        for local_file, storage_path, json_key in uploads:
            public_url = _upload_blob(bucket, local_file, storage_path)
            url_map[(os.path.basename(local_file), json_key)] = public_url
            uploaded += 1
            print(f"  Загружено: {storage_path} -> {public_url}")

        for content in site.get("arContents", []):
            url_file = _resolve_local_file(content.get("url"))
            if url_file:
                content["url"] = url_map[(os.path.basename(url_file), "url")]
            thumb_file = _resolve_local_file(content.get("thumbnailURL"))
            if thumb_file:
                content["thumbnailURL"] = url_map[(os.path.basename(thumb_file), "thumbnailURL")]

        db.collection(COLLECTION_NAME).document(site_id).set(site)
        print(f"Документ записан: {COLLECTION_NAME}/{site_id}")

    print(f"Готово. Загружено файлов в Storage: {uploaded}, документов: {len(sites)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
