#!/bin/sh
export PYTHONPATH="@PREFIX@/share/doubao-say${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m doubao_input "$@"
