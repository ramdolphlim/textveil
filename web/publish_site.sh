#!/bin/bash
# 文隐 TextVeil · 把 web/dist 发布到本仓库的 site 分支，Cloudflare Worker（src/worker.js）从这里取文件。
#
# site 分支结构：
#   index.html favicon.svg icon.png robots.txt   根目录，页面入口（Worker 短缓存）
#   <版本号>/app.js app.css engine.zip ...         带版本号的资源（Worker 长缓存）
# 保留「当前版本 + 上一个版本」，刚好在更新时打开页面的人也不会拿到对不上的文件。
# 每次发布都是一个独立提交（强制推送），site 分支不会越积越大。
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE=${1:-origin}
V=$(tr -d '[:space:]' < web/dist/VERSION)
NEW=$(mktemp -d)
OLD=$(mktemp -d)
if git fetch -q --depth 1 "$REMOTE" site 2>/dev/null; then
  git archive FETCH_HEAD | tar -x -C "$OLD"
fi
PREV=$(grep -o 'v=[0-9a-f]\{10\}' "$OLD/index.html" 2>/dev/null | head -1 | cut -c3- || true)
if [ -n "$PREV" ] && [ "$PREV" != "$V" ] && [ -d "$OLD/$PREV" ]; then cp -R "$OLD/$PREV" "$NEW/$PREV"; fi
mkdir -p "$NEW/$V"
cp web/dist/* "$NEW/$V/"
cp web/dist/index.html web/dist/favicon.svg web/dist/icon.png web/dist/robots.txt "$NEW/"
GD=$(git rev-parse --absolute-git-dir)
export GIT_INDEX_FILE=$(mktemp -u)
(cd "$NEW" && git --git-dir="$GD" --work-tree=. add -A)
TREE=$(git write-tree)
COMMIT=$(git -c user.name="${GIT_AUTHOR_NAME:-github-actions[bot]}" -c user.email="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
  commit-tree "$TREE" -m "site $V（来自 $(git rev-parse --short HEAD)）")
git push -q -f "$REMOTE" "$COMMIT:refs/heads/site"
rm -f "$GIT_INDEX_FILE"
echo "已发布网页版 $V 到 site 分支（保留上一版本：${PREV:-无}）"
