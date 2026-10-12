#!/bin/sh
# Invoked only after the native updater verifies the staged Developer ID app.
set -eu
staged=$1
target=$2
old_pid=$3
backup=$4
lock="$target.update-lock"
/bin/mkdir "$lock"
trap '/bin/rmdir "$lock"' EXIT
[ ! -L "$target" ]
count=0
while kill -0 "$old_pid" 2>/dev/null; do
    count=$((count + 1))
    if [ "$count" -ge 100 ]; then exit 1; fi
    sleep 0.1
done
/usr/bin/codesign --verify --deep --strict "$staged"
/usr/bin/codesign --verify --deep --strict "$target"
old_team=$(/usr/bin/codesign -d --verbose=4 "$target" 2>&1 | /usr/bin/sed -n 's/^TeamIdentifier=//p')
new_team=$(/usr/bin/codesign -d --verbose=4 "$staged" 2>&1 | /usr/bin/sed -n 's/^TeamIdentifier=//p')
[ -n "$old_team" ] && [ "$old_team" != not\ set ] && [ "$old_team" = "$new_team" ]
[ ! -e "$backup" ]
/bin/mv "$target" "$backup"
if ! /bin/mv "$staged" "$target"; then
    /bin/mv "$backup" "$target"
    /usr/bin/open "$target"
    exit 1
fi
if ! /usr/bin/open "$target"; then
    /bin/mv "$target" "$staged"
    /bin/mv "$backup" "$target"
    /usr/bin/open "$target"
    exit 1
fi
