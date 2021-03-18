# otuserver
Простой многопоточный http сервер.

### Конфигурирование

Конфигурирование реализовано через параметры командной строки.
```
-r - site root path
-w - number of workers
```
Port  8080.

## Запуск

python3 httpd.py -r /site/root -w 2
