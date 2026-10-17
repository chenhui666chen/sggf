#!/bin/bash
echo "=====F1. /var/log 全量列表====="
ls -lah /var/log/ | grep -vE '^total'
echo
echo "=====F2. 全盘搜 messages/cron/secure 轮转文件====="
find /var/log /var/lib/docker/containers -maxdepth 2 -name 'messages*' -o -maxdepth 2 -name 'cron-*' -o -maxdepth 2 -name 'secure-*' 2>/dev/null
echo
echo "=====F3. logrotate.service 运行历史（09:37 后到底跑了几次）====="
journalctl -u logrotate.service --no-pager --since '2026-10-16 09:30' 2>/dev/null | tail -30
echo
echo "=====F4. journal 持久化与占用（日志是否还有第二份）====="
ls -la /var/log/journal/ 2>/dev/null | head -5
journalctl --disk-usage 2>/dev/null
echo
echo "=====F5. cron 日志链路实测（生成一条 CRON 记录）====="
logger -p cron.info -t CRONTEST "cron log path probe $(date +%H:%M:%S)"
sleep 1
ls -la /var/log/cron 2>&1
tail -3 /var/log/cron 2>&1
echo "--- messages 里有无 cron 记录 ---"
grep -c CRONTEST /var/log/messages 2>/dev/null
echo
echo "=====F6. 根分区水位（旧文件若被删空间应释放）====="
df -h / | tail -1
echo
echo "=====F7. rsyslog 当前打开的日志文件句柄====="
ls -l /proc/$(pgrep -x rsyslogd)/fd/ 2>/dev/null | grep -E 'messages|cron|secure' | head -10
echo "=====FIND DONE====="
