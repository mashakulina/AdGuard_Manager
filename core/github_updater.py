import urllib.request
import urllib.error

class GitHubUpdater:
    def __init__(self, version_url, current_version):
        self.version_url = version_url
        self.current_version = current_version

    def check_for_updates(self):
        """Проверяет наличие обновлений через простой txt файл"""
        try:
            # Скачиваем файл версий
            with urllib.request.urlopen(self.version_url, timeout=10) as response:
                content = response.read().decode('utf-8').strip()

            # Парсим файл (формат: версия\nurl)
            lines = content.split('\n')
            if len(lines) >= 2:
                latest_version = lines[0].strip()
                download_url = lines[1].strip()

                # Сравниваем версии
                if self.is_newer_version(latest_version, self.current_version):
                    return latest_version, {
                        'download_url': download_url,
                        'description': f'Доступна новая версия менеджера: {latest_version}'
                    }

            if len(lines) < 2 or not lines[0].strip() or not lines[1].strip():
                raise ValueError("Некорректный ответ сервера версий менеджера")
            return None, None

        except Exception:
            # Propagate transport/format errors; callers must not report latest.
            raise

    def is_newer_version(self, latest, current):
        """Простое сравнение версий"""
        # Убираем 'v' префикс если есть
        latest_clean = latest.replace('v', '')
        current_clean = current.replace('v', '')

        # Простое строковое сравнение (для семантического версионирования это работает)
        return latest_clean > current_clean

    def get_download_url(self, release_data):
        """Получает URL для скачивания"""
        return release_data.get('download_url', '') if release_data else ''

    def get_release_description(self, release_data):
        """Получает описание релиза"""
        return release_data.get('description', 'Доступно обновление менеджера') if release_data else ''
