# 两道闸共用一份凭据形态：pre-commit 扫暂存区，pre-push 扫真要推上去的对象。
# 改这里等于同时改两道，别让它们俩跑偏。
#
# 这些正则是「形态」不是「值」。每一条都刻意带转义或长度门槛，所以扫到本仓库自己的
# hook / 沙箱 / 文档时不会自己咬自己：文件里写的是 push\.ft07\.com，正则要的是 push.ft07.com。

# ServerChan 的 send token 与两种端点形状、私钥、GitHub PAT、Slack token、AKIA 系临时密钥
PATTERNS='sct[0-9a-zA-Z]{20,}|SCT[0-9]{4,}[0-9a-zA-Z]{10,}|push\.ft07\.com/send/|sct\.ftqq\.com/send/|-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[0-9A-Za-z]{30,}|xox[baprs]-[0-9A-Za-z-]{10,}|ASIA[0-9A-Z]{16}'
