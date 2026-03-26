#!/bin/bash
set -e

echo ""
echo "================================================"
echo "  🚀 Stepik Auto-Solver Bot"
echo "================================================"
echo ""

# 0. Чистим lock-файлы от предыдущего запуска
echo "🧹 Очистка..."
rm -f /tmp/.X99-lock
rm -rf /tmp/.X11-unix/X99

# 1. Xvfb
echo "📺 Запуск Xvfb..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &

echo "   Ожидание готовности Xvfb..."
for i in $(seq 1 30); do
    if xdpyinfo -display :99 > /dev/null 2>&1; then
        echo "   ✅ Xvfb готов (за ${i} сек)"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "   ❌ Xvfb не запустился!"
        exit 1
    fi
    sleep 1
done

export DISPLAY=:99

# 2. Fluxbox
echo "🪟 Запуск fluxbox..."
fluxbox -no-slit -no-toolbar > /dev/null 2>&1 &
sleep 1

# 3. x11vnc  (ИСПРАВЛЕНО: -rfbport вместо -port)
echo "🔗 Запуск x11vnc..."
x11vnc -display :99 -nopw -listen 0.0.0.0 -rfbport 5900 \
       -forever -shared -noxdamage -noxfixes &
sleep 3

if pgrep -x x11vnc > /dev/null 2>&1; then
    echo "   ✅ x11vnc работает"
else
    echo "   ❌ x11vnc не запустился!"
    exit 1
fi

# 4. noVNC
echo "🌐 Запуск noVNC..."
websockify --web /usr/share/novnc/ 6080 localhost:5900 > /dev/null 2>&1 &
sleep 2

if pgrep -x websockify > /dev/null 2>&1; then
    echo "   ✅ noVNC работает"
else
    echo "   ❌ noVNC не запустился!"
    exit 1
fi

# 5. Информация
if [ -f /app/cookies/stepik_cookies.json ]; then
    echo ""
    echo "🍪 Найдены сохранённые cookies!"
    echo "   Бот попробует войти автоматически."
    echo ""
else
    echo ""
    echo "══════════════════════════════════════════════"
    echo ""
    echo "  🔑 ПЕРВЫЙ ЗАПУСК"
    echo ""
    echo "  Откройте в браузере:"
    echo "  👉 http://localhost:6080/vnc.html"
    echo ""
    echo "  Нажмите 'Подключение', затем залогиньтесь"
    echo "  на Stepik в появившемся окне Chromium."
    echo ""
    echo "══════════════════════════════════════════════"
    echo ""
fi

# 6. Запуск бота
echo "🤖 Запуск бота..."
python -m src.main
BOT_EXIT_CODE=$?

if [ $BOT_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Бот завершился с ошибкой (код: $BOT_EXIT_CODE)"
    echo "   VNC всё ещё работает для диагностики."
    echo ""
    tail -f /dev/null
else
    echo "✅ Бот завершился успешно."
fi