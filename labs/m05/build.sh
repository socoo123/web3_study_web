#!/usr/bin/env bash
# Java 21 + Maven 3.9.x. After preparing dependencies, pass -o for offline use.
set -euo pipefail
cd "$(dirname "$0")"
mvn -B "$@" compile dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
