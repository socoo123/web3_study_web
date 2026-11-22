#!/usr/bin/env bash
# Dedicated disposable cluster. PostgreSQL does not listen on the LAN.
set -euo pipefail
name=m05-course-postgres
db=${M05_DB:-m05}
[[ $db =~ ^m05(_[a-z0-9]+)?$ ]] || { echo 'M05_DB 必须是 m05 或 m05_<小写字母数字>' >&2; exit 2; }
if [[ ${1:-} != start ]]; then
    [[ $(docker inspect --format '{{index .Config.Labels "chain.course.lab"}}' "$name") == m05 ]] || { echo '不是本卷的临时容器' >&2; exit 2; }
fi
case ${1:-} in
    start)
        docker run --rm -d --name "$name" --label chain.course.lab=m05 \
            --tmpfs /var/lib/postgresql/data -p 127.0.0.1:18557:5432 \
            -e POSTGRES_DB=m05 -e POSTGRES_USER=course -e POSTGRES_PASSWORD=course-local postgres:17.5-bookworm
        for ((i=0; i<60; i++)); do
            if docker exec "$name" pg_isready -q -h 127.0.0.1 -U course -d m05; then exit 0; fi
            sleep 1
        done
        echo 'PostgreSQL 未就绪，查看 docker logs m05-course-postgres' >&2; exit 1 ;;
    sql) exec docker exec -i "$name" psql -X -v ON_ERROR_STOP=1 -U course -d "$db" ;;
    dump) exec docker exec "$name" pg_dump -Fc -U course -d "$db" ;;
    restore)
        # Never overlay an existing database. Send a custom-format dump via stdin.
        docker exec "$name" createdb -U course "$db"
        exec docker exec -i "$name" pg_restore -1 -e -U course -d "$db" ;;
    stop) exec docker stop "$name" ;;
    *) echo 'db.sh start | sql | dump | restore | stop（stop 会清除整个临时库，先 dump）' >&2; exit 2 ;;
esac
