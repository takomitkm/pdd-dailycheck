#!/usr/bin/env bash
# 负对照：把「BACK 落在频道页就点胶囊回活动页」那一枪的判据改成恒假，
# browse-reenter-venue 这条必须挂；挂了就说明它真的在钉那段代码，不是白过的。
#
# 前置：先跑过 scripts/run-sandbox.sh（它把 /tmp/pddsandbox/in 铺好），本脚本在那份拷贝上改。
# 判据的锚点是 `text_present bag; then`，改 pdd.sh 里这句话时记得同步这里的 sed。
set -u
SS=(ssh -4 -o ConnectTimeout=10 deb-h61)
NEG=/tmp/pddsandbox-neg

"${SS[@]}" "set -u
[ -d /tmp/pddsandbox/in ] || { echo '没有 /tmp/pddsandbox/in，先跑 scripts/run-sandbox.sh'; exit 1; }
rm -rf $NEG; mkdir -p $NEG
cp -a /tmp/pddsandbox/in $NEG/in
sed -i 's#text_present bag; then#false; then#' $NEG/in/pdd.sh
grep -q 'false; then' $NEG/in/pdd.sh || { echo 'NEG_PATCH_FAILED：源码里找不到那句判据，负对照没做成'; exit 1; }
grep -n 'false; then' $NEG/in/pdd.sh
SBX_IN=$NEG/in SBX_ROOT=$NEG/run ONLY=browse-reenter-venue bash $NEG/in/sbx.sh 2>&1 | tail -6"
echo "NEGCHECK_DONE（上面这条用例应当是 ✗）"
