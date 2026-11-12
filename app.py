#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
球队近况 - 手机版
输入球队名，显示最近 N 场：比分、对手、双方绝佳机会 / 错失绝佳机会、球员评分与上场情况。

运行：双击 启动.bat，或命令行 python app.py
手机：与电脑连同一个 WiFi，浏览器打开 http://<电脑内网IP>:8000
数据：Sofascore 公开接口（非官方），仅本地查看用。
"""

import html
import json
import os
import ssl
import shutil
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_HOSTS = ["api.sofascore.com", "www.sofascore.com"]
API = "https://" + API_HOSTS[0] + "/api/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
CACHE_TTL = 60 * 30          # 赛事数据缓存 30 分钟
DEFAULT_N = 5

os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------- 中文队名 → 英文
# 同一支球队收录：简体、繁体/粤语、绰号、简称。打错一两个字也能靠模糊匹配兜住。
def norm(q):
    """归一化：去空格、去俱乐部/队/FC 这类后缀。"""
    s = (q or "").strip().lower()
    s = s.replace("\u3000", "").replace(" ", "").replace("\u00b7", "")
    s = s.replace("-", "").replace(".", "").replace("_", "")
    for suf in ("\u8db3\u7403\u4ff1\u4e50\u90e8", "\u4ff1\u4e50\u90e8", "fc", "cf", "\u961f", "\u968a"):
        if len(s) > len(suf) + 1 and s.endswith(suf):
            s = s[: -len(suf)]
    return s


ALIAS = {}


def _add(en, *names):
    for n in names:
        key = norm(n)
        if key:
            ALIAS[key] = en


_add("Arsenal", "阿森纳", "阿仙奴", "阿森納", "枪手", "兵工厂", "兵工廠")
_add("Liverpool", "利物浦", "红军", "紅軍")
_add("Manchester City", "曼城", "曼城队", "蓝月亮", "藍月亮", "曼彻斯特城", "曼城足球俱乐部")
_add("Manchester United", "曼联", "曼聯", "红魔", "紅魔", "曼彻斯特联")
_add("Chelsea", "切尔西", "車路士", "蓝军", "藍軍")
_add("Tottenham", "热刺", "熱刺", "托特纳姆", "托特纳姆热刺", "白百合", "热刺队")
_add("Newcastle", "纽卡斯尔", "纽卡", "紐卡素", "喜鹊")
_add("Aston Villa", "阿斯顿维拉", "维拉", "阿士東維拉", "維拉")
_add("Brighton", "布莱顿", "白禮頓", "海鸥", "白海鸥")
_add("Everton", "埃弗顿", "愛華頓", "太妃糖")
_add("West Ham", "西汉姆", "西漢姆", "韦斯咸", "鐵鎚幫", "铁锤帮")
_add("Crystal Palace", "水晶宫", "水晶宮", "老鹰", "老鷹")
_add("Fulham", "富勒姆", "富咸", "农场主")
_add("Brentford", "布伦特福德", "布倫特福德", "蜜蜂")
_add("Wolves", "狼队", "狼隊", "伍尔弗汉普顿", "狼")
_add("Nottingham Forest", "诺丁汉森林", "森林", "諾定咸森林")
_add("Bournemouth", "伯恩茅斯", "般尼茅夫", "樱桃")
_add("Leeds", "利兹联", "列斯联", "列斯聯", "利兹")
_add("Burnley", "伯恩利", "般尼")
_add("Sunderland", "桑德兰", "新特蘭", "黑猫")
_add("Leicester", "莱斯特城", "李斯特城", "狐狸", "莱斯特")
_add("Southampton", "南安普顿", "修咸頓", "圣徒")
_add("Sheffield United", "谢菲尔德联", "錫菲聯", "谢菲联")
_add("Middlesbrough", "米德尔斯堡", "米杜士堡")
_add("West Brom", "西布朗", "西布朗维奇")
_add("Norwich", "诺维奇", "諾域治")
_add("Watford", "沃特福德", "屈福特")
_add("Swansea", "斯旺西", "史雲斯")
_add("Cardiff", "卡迪夫城", "卡迪夫")
_add("Wrexham", "雷克瑟姆", "域斯咸")

_add("Real Madrid", "皇马", "皇馬", "皇家马德里", "皇家馬德里", "银河战舰", "銀河艦隊", "马德里")
_add("Barcelona", "巴萨", "巴塞罗那", "巴塞隆拿", "巴塞", "巴萨罗那")
_add("Atletico Madrid", "马竞", "馬體會", "马德里竞技", "馬德里體育會", "床单军团")
_add("Sevilla", "塞维利亚", "西維爾", "塞維利亞")
_add("Real Sociedad", "皇家社会", "皇家蘇斯達")
_add("Villarreal", "比利亚雷亚尔", "維拉利爾", "黄色潜水艇", "黄潜")
_add("Athletic Bilbao", "毕尔巴鄂", "毕尔巴鄂竞技", "畢爾包")
_add("Real Betis", "贝蒂斯", "貝迪斯", "皇家贝蒂斯")
_add("Valencia", "巴伦西亚", "瓦伦西亚", "華倫西亞")
_add("Girona", "赫罗纳", "基羅納")
_add("Celta Vigo", "塞尔塔", "切爾達")
_add("Mallorca", "马略卡", "馬略卡")
_add("Osasuna", "奥萨苏纳", "奧沙辛拿")
_add("Getafe", "赫塔菲", "基達菲")

_add("Bayern Munich", "拜仁", "拜仁慕尼黑", "拜仁慕尼黑足球俱乐部", "南大王")
_add("Borussia Dortmund", "多特", "多特蒙德", "多蒙特", "大黄蜂", "大黃蜂")
_add("Bayer Leverkusen", "勒沃库森", "利华古逊", "利華古遜", "药厂", "藥廠")
_add("RB Leipzig", "莱比锡", "萊比錫", "莱比锡红牛", "RB莱比锡")
_add("Eintracht Frankfurt", "法兰克福", "法蘭克福")
_add("Stuttgart", "斯图加特", "斯圖加特")
_add("Freiburg", "弗莱堡", "弗賴堡")
_add("Wolfsburg", "沃尔夫斯堡", "沃爾夫斯堡", "狼堡")
_add("Union Berlin", "柏林联合", "柏林聯")
_add("Werder Bremen", "不莱梅", "云达不莱梅", "雲達不萊梅")
_add("Hoffenheim", "霍芬海姆", "賀芬咸")
_add("Mainz", "美因茨", "緬恩斯")

_add("Juventus", "尤文", "尤文图斯", "祖雲達斯", "祖记", "斑马军团")
_add("Inter", "国米", "國際米蘭", "国际米兰", "国米队", "蓝黑军团")
_add("AC Milan", "AC米兰", "AC米蘭", "米兰", "米蘭", "紅黑軍團")
_add("Napoli", "那不勒斯", "拿玻里", "拿坡里")
_add("Roma", "罗马", "羅馬", "红狼")
_add("Lazio", "拉齐奥", "拉素", "拉齊奧")
_add("Atalanta", "亚特兰大", "阿特蘭大", "真蓝黑")
_add("Fiorentina", "佛罗伦萨", "費倫天拿", "紫百合")
_add("Bologna", "博洛尼亚", "博洛尼亞")
_add("Torino", "都灵", "拖連奴")
_add("Udinese", "乌迪内斯", "烏甸尼斯")
_add("Genoa", "热那亚", "熱拿亞")
_add("Sassuolo", "萨索洛", "莎索羅")

_add("Paris Saint-Germain", "巴黎", "巴黎圣日耳曼", "巴黎聖日耳門", "PSG", "大巴黎")
_add("Monaco", "摩纳哥", "摩納哥")
_add("Marseille", "马赛", "馬賽")
_add("Lyon", "里昂", "里昂队")
_add("Lille", "里尔", "里爾")
_add("Nice", "尼斯", "奈斯")
_add("Rennes", "雷恩", "雷恩队")
_add("Lens", "朗斯", "朗斯队")
_add("Nantes", "南特", "南特队")
_add("Strasbourg", "斯特拉斯堡", "史特拉斯堡")

_add("Ajax", "阿贾克斯", "阿積士", "阿亚克斯")
_add("PSV", "埃因霍温", "燕豪芬", "PSV埃因霍温", "psv")
_add("Feyenoord", "费耶诺德", "飛燕諾", "飞燕诺")
_add("AZ Alkmaar", "阿尔克马尔", "AZ", "阿爾克馬爾")
_add("Twente", "特温特", "川迪")

_add("Porto", "波尔图", "波圖", "波图")
_add("Benfica", "本菲卡", "賓菲加", "宾菲加")
_add("Sporting CP", "葡萄牙体育", "士砵亭", "里斯本竞技", " Sporting", "士砵亭里斯本")
_add("Braga", "布拉加", "布拉加队")

_add("Galatasaray", "加拉塔萨雷", "加拉塔沙雷", "加拉塔沙雷队")
_add("Fenerbahce", "费内巴切", "費倫巴治", "费伦巴治")
_add("Besiktas", "贝西克塔斯", "比錫達斯")
_add("Trabzonspor", "特拉布宗", "特拉布宗体育")

_add("Celtic", "凯尔特人", "些路迪", "塞尔提克")
_add("Rangers", "流浪者", "格拉斯哥流浪", "格拉斯哥流浪者", "格流")
_add("Olympiacos", "奥林匹亚科斯", "奧林比亞高斯")
_add("Panathinaikos", "帕纳辛奈科斯", "彭拿典奈高斯")
_add("AEK Athens", "雅典AEK", "AEK雅典", "AEK")
_add("PAOK", "塞萨洛尼基", "PAOK")
_add("Red Star Belgrade", "贝尔格莱德红星", "貝爾格萊德紅星", "红星")
_add("Partizan", "贝尔格莱德游击", "柏迪逊")
_add("Dinamo Zagreb", "萨格勒布迪纳摩", "薩格勒布戴拿模")
_add("Slavia Prague", "布拉格斯拉维亚", "布拉格斯拉維亞")
_add("Sparta Prague", "布拉格斯巴达", "布拉格斯巴達")
_add("Legia Warsaw", "华沙莱吉亚", "歷基亞")
_add("Copenhagen", "哥本哈根", "哥本哈根队")
_add("Club Brugge", "布鲁日", "布魯日")
_add("Anderlecht", "安德莱赫特", "安德列治")
_add("Salzburg", "萨尔茨堡", "薩爾斯堡", "红牛萨尔茨堡")
_add("Basel", "巴塞尔", "巴塞爾")
_add("Young Boys", "伯尔尼年轻人", "年青人")
_add("Shakhtar", "顿涅茨克矿工", "礦工", "矿工", "薩克達", "萨克达", "顿矿")
_add("Dynamo Kyiv", "基辅迪纳摩", "基輔戴拿模")
_add("Zenit", "泽尼特", "辛尼特")
_add("Spartak Moscow", "莫斯科斯巴达", "斯巴达")
_add("Al Hilal", "利雅得新月", "希拉尔")
_add("Al Nassr", "利雅得胜利", "艾纳斯")
_add("Inter Miami", "迈阿密国际", "国际迈阿密")
_add("Flamengo", "弗拉门戈", "法林明高")
_add("Palmeiras", "帕尔梅拉斯", "彭美拉斯")
_add("River Plate", "河床", "河床队")
_add("Boca Juniors", "博卡青年", "小保加")


def _dice(a, b):
    """字符二元组相似度，0~1。中文名打错一两个字也能对上。"""
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 1.0 if (a in b or b in a) else 0.0
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    return 2.0 * len(A & B) / (len(A) + len(B))


LEARNED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aliases.json")
_LEARN_LOCK = threading.Lock()


def load_learned():
    try:
        with open(LEARNED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def learn(zh, team_id, name):
    """用户选过一次，就把「他打的中文 → 这支球队」记下来，下次直接命中。"""
    key = norm(zh)
    if not key or not team_id or not name:
        return
    with _LEARN_LOCK:
        d = load_learned()
        if d.get(key, {}).get("id") == team_id:
            return
        d[key] = {"id": team_id, "name": name}
        try:
            with open(LEARNED_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


def _is_ascii_word(s):
    return bool(s) and all(ord(ch) < 128 for ch in s)


def guess_terms(q):
    """把用户输入变成若干个英文搜索词，按可信度排序（最多 3 个）。"""
    raw = (q or "").strip()
    key = norm(raw)
    if not key:
        return []
    out = []

    def push(x):
        x = (x or "").strip()
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)

    if _is_ascii_word(raw):
        push(raw)
    learned = load_learned()
    if key in learned:
        push(learned[key]["name"])
        return out[:3]
    if key in ALIAS:
        push(ALIAS[key])
        return out[:3]
    for zh, en in ALIAS.items():          # 包含匹配
        if zh and (zh in key or (len(zh) >= 3 and key in zh)):
            push(en)
            if len(out) >= 3:
                break
    if len(out) < 2 and len(key) >= 4:    # 模糊：至少 4 个字才猜，避免 psg/psv 误伤
        scored = sorted(((_dice(key, zh), en) for zh, en in ALIAS.items()), reverse=True)
        for sc, en in scored:
            if sc >= 0.5:
                push(en)
            if len(out) >= 3:
                break
    if not out:
        push(raw)
    return out[:3]


# ---------------------------------------------------------------- 抓取与缓存
_CTX = None


class NetError(Exception):
    """带上失败原因的异常，方便前端/诊断页说人话。"""

    def __init__(self, kind, msg, host=""):
        self.kind = kind
        self.msg = msg
        self.host = host
        super().__init__("%s: %s" % (kind, msg))


HINT = {
    "dns": "域名解析失败：电脑没联网 / DNS 被拦 / 需要挂代理。",
    "refused": "连接被拒绝：本机防火墙或安全软件拦了 443 端口出口。",
    "timeout": "连接超时：这个域名在你当前的网络下连不通（常见于国内直连）。挂上代理再试。",
    "tls": "TLS 握手失败：多半是代理/杀毒软件做了证书拦截，或系统时间不对。",
    "403": "数据源拒绝访问（403）：你的请求被 Cloudflare 当成脚本拦了（TLS 指纹问题），换浏览器型引擎或代理。",
    "4xx": "数据源返回错误状态。",
    "5xx": "数据源自己出错了，等几分钟再试。",
    "badjson": "返回内容不是 JSON，可能被代理/运营商劫持插入了页面。",
    "offline": "网络不可用。",
}


def _ctx_no_verify():
    global _CTX
    if _CTX is None:
        _CTX = ssl.create_default_context()
        _CTX.check_hostname = False
        _CTX.verify_mode = ssl.CERT_NONE
    return _CTX


PROXY_FILE = os.path.join(BASE_DIR, "proxy.txt")


def proxy_url():
    """优先 proxy.txt，其次环境变量，最后 Windows 系统代理。"""
    for env in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        v = os.environ.get(env)
        if v:
            return v.strip()
    try:
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except Exception:
        pass
    try:
        p = urllib.request.getproxies()
        for k in ("https", "http"):
            if p.get(k):
                return p[k]
    except Exception:
        pass
    return None


def _opener(ctx=None):
    handlers = []
    px = proxy_url()
    if px:
        if "://" not in px:
            px = "http://" + px
        handlers.append(urllib.request.ProxyHandler({"http": px, "https": px}))
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _fetch_once(url, timeout, ctx=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
        "Connection": "keep-alive",
    })
    op = _opener(ctx)
    try:
        with op.open(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code = e.code
        kind = "403" if code == 403 else ("5xx" if code >= 500 else "4xx")
        raise NetError(kind, "HTTP %d" % code, url.split("/")[2])
    except urllib.error.URLError as e:
        r = e.reason
        if isinstance(r, socket.gaierror):
            raise NetError("dns", str(r), url.split("/")[2])
        if isinstance(r, ConnectionRefusedError):
            raise NetError("refused", str(r), url.split("/")[2])
        if isinstance(r, (socket.timeout, TimeoutError)):
            raise NetError("timeout", str(r), url.split("/")[2])
        if isinstance(r, ssl.SSLError):
            raise NetError("tls", str(r), url.split("/")[2])
        msg = str(r)
        kind = "timeout" if ("timed out" in msg.lower() or "超时" in msg) else "offline"
        raise NetError(kind, msg, url.split("/")[2])
    except (socket.timeout, TimeoutError) as e:
        raise NetError("timeout", str(e), url.split("/")[2])
    except ssl.SSLError as e:
        raise NetError("tls", str(e), url.split("/")[2])
    try:
        return json.loads(raw)
    except Exception:
        raise NetError("badjson", raw[:80], url.split("/")[2])


_PREF = {"engine": "urllib"}


def http_json(url, timeout=15, retries=1):
    """抓 JSON：直连不通时会自动换 curl / 浏览器指纹 / 无头浏览器 / 中转，并记住能用的那个。"""
    if _PREF["engine"] == "curl_cffi":
        try:
            return _fetch_via_curl_cffi(url, timeout)
        except NetError:
            _PREF["engine"] = "urllib"
    elif _PREF["engine"] == "browser":
        try:
            return _fetch_via_browser(url, max(30, timeout))
        except NetError:
            _PREF["engine"] = "urllib"
    elif _PREF["engine"] == "relay":
        d = _try_relays(url, max(15, timeout))
        if d is not None:
            return d
        _PREF["engine"] = "urllib"

    hosts = []
    for h in API_HOSTS:
        if url.startswith("https://" + h + "/"):
            hosts = [x for x in API_HOSTS if x != h]
            hosts.insert(0, h)
            rest = url[len("https://" + h):]
            break
    if not hosts:
        hosts, rest = [None], None

    last = None
    for host in hosts:
        target = ("https://" + host + rest) if rest is not None else url
        for i in range(retries + 1):
            try:
                return _fetch_once(target, timeout)
            except NetError as e:
                last = e
                if e.kind == "tls":                      # 证书被拦，退一步不校验再试一次
                    try:
                        return _fetch_once(target, timeout, ctx=_ctx_no_verify())
                    except NetError as e2:
                        last = e2
                if e.kind in ("dns", "refused"):
                    break                                # 这个域名整体不通，直接换下一个
            except Exception as e:                        # 兜底
                last = NetError("offline", str(e), host or "")
            if i < retries:
                time.sleep(0.8 * (i + 1))
    # 直连全挂（超时/被拒/403）→ 换系统 curl 再试，它更不容易被拦
    if last is not None and last.kind in ("403", "timeout", "tls", "offline", "badjson", "4xx", "5xx"):
        try:
            d = _fetch_via_curl(target if rest is not None else url, min(timeout, 20))
            if isinstance(d, dict):
                print("  · 改用 curl 取数成功，后续都走它")
                return d
        except NetError as e:
            curl_err = e      # 只记录，不覆盖直连失败的真实原因（报告里分开说）

    # 403 多半是 TLS 指纹被识别 → 换浏览器指纹的 curl_cffi
    if last is not None and last.kind in ("403", "4xx", "timeout", "offline", "badjson", "5xx", "tls"):
        try:
            d = _fetch_via_curl_cffi(url, min(timeout, 20))
            if isinstance(d, dict):
                print("  · 改用 curl_cffi（浏览器指纹）取数成功，后续都走它")
                _PREF["engine"] = "curl_cffi"
                return d
        except NetError:
            pass
        try:
            d = _fetch_via_browser(url, 35)
            if isinstance(d, dict):
                print("  · 改用本机浏览器取数成功，后续都走它")
                _PREF["engine"] = "browser"
                return d
        except NetError:
            pass

    # 还不行 → 试公共中转，很多网络里它们是通的
    if last is not None and last.kind in ("timeout", "dns", "offline", "refused", "403"):
        d = _try_relays(target if rest is not None else url, min(timeout, 20))
        if d is not None:
            _PREF["engine"] = "relay"
            return d
    raise last or NetError("offline", "未知错误")


RELAYS = [
    ("allorigins", lambda u: "https://api.allorigins.win/raw?url=" + urllib.parse.quote(u, safe="")),
    ("corsproxy", lambda u: "https://corsproxy.io/?" + urllib.parse.quote(u, safe="")),
    ("jina", lambda u: "https://r.jina.ai/" + u),
]


CURL = shutil.which("curl") or "curl"


def _fetch_via_curl(url, timeout):
    """用系统自带 curl 再试一次：它的 TLS 指纹更像真浏览器，能绕开一些拦 Python 的地方。"""
    if not CURL:
        raise NetError("offline", "没有 curl")
    px = proxy_url()
    cmd = [CURL, "-sS", "--compressed", "--max-time", str(int(timeout)),
           "-A", UA,
           "-H", "Accept: application/json, text/plain, */*",
           "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
           "-H", "Referer: https://www.sofascore.com/",
           "-H", "Origin: https://www.sofascore.com",
           "-w", "\n%{http_code}", url]
    if px:
        cmd[1:1] = ["-x", px if "://" in px else "http://" + px]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 8)
    except Exception as e:
        raise NetError("offline", "curl 无法运行：%s" % e)
    raw = (out.stdout or b"").decode("utf-8", "replace")
    if "\n" not in raw:
        raise NetError("badjson", raw[:80])
    body, _, code = raw.rpartition("\n")
    code = code.strip()
    if code != "200":
        kind = "403" if code == "403" else ("5xx" if code[:1] == "5" else "4xx")
        raise NetError(kind, "curl HTTP %s" % code)
    try:
        return json.loads(body)
    except Exception:
        raise NetError("badjson", body[:80])


def _fetch_via_curl_cffi(url, timeout):
    """curl_cffi 会伪装成 Chrome 的 TLS 指纹，Cloudflare 基本拦不住。需要 pip install curl_cffi。"""
    try:
        from curl_cffi import requests as creq
    except Exception:
        raise NetError("offline", "未安装 curl_cffi")
    try:
        r = creq.get(url, impersonate="chrome", timeout=timeout,
                     headers={"Referer": "https://www.sofascore.com/",
                              "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                     proxies={"http": proxy_url(), "https": proxy_url()} if proxy_url() else None)
    except Exception as e:
        raise NetError("offline", "curl_cffi 失败：%s" % str(e)[:80])
    if r.status_code != 200:
        kind = "403" if r.status_code == 403 else ("5xx" if r.status_code >= 500 else "4xx")
        raise NetError(kind, "curl_cffi HTTP %d" % r.status_code)
    try:
        return r.json()
    except Exception:
        raise NetError("badjson", r.text[:80])


BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def browser_exe():
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    return None


def _json_from_page(page):
    """从无头浏览器的 --dump-dom 输出里挖出真正的 JSON（拿不到就返回 None）。"""
    NEED = ("results", "events", "statistics", "home", "away", "teams", "match")
    cands = re.findall(r"<pre[^>]*>(.*?)</pre>", page, re.S)
    cands.append(page)
    for c in cands:
        t = html.unescape(c).strip()
        i = t.find("{")
        if i < 0:
            continue
        frag = t[i:]
        j = frag.rfind("}")
        if j > 0:
            frag = frag[:j + 1]
        try:
            d = json.loads(frag)
        except Exception:
            continue
        if isinstance(d, dict) and any(k in d for k in NEED):
            return d
    return None


def _fetch_via_browser(url, timeout=30):
    """用本机装好的 Edge/Chrome 无头模式取一次——它就是真浏览器，Cloudflare 不会拦。"""
    exe = browser_exe()
    if not exe:
        raise NetError("offline", "没找到 Edge/Chrome")
    import tempfile
    last = ""
    for budget in (8000, 20000):
        td = tempfile.mkdtemp(prefix="teamform_")
        try:
            cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-extensions", "--disable-background-networking", "--hide-scrollbars",
                   "--user-data-dir=" + td, "--virtual-time-budget=%d" % budget,
                   "--dump-dom", url]
            out = subprocess.run(cmd, capture_output=True, timeout=timeout)
            page = (out.stdout or b"").decode("utf-8", "replace")
        except Exception as e:
            last = "无头浏览器失败：%s" % str(e)[:80]
            continue
        finally:
            try:
                import shutil as _sh
                _sh.rmtree(td, ignore_errors=True)
            except Exception:
                pass
        if not page.strip():
            last = "浏览器没有输出（可能被安全软件拦住）"
            continue
        d = _json_from_page(page)
        if d is not None:
            return d
        empty_pre = ("<pre" in page) and (not re.search(r"<pre[^>]*>\s*\S", page))
        if empty_pre or len(page) < 600:
            last = "浏览器拿到的是一张空页（%d 字节）：服务器直接回绝了，基本就是网络出口被封" % len(page)
        else:
            last = "页面里没有数据（%d 字节，可能停在验证页）" % len(page)
    raise NetError("badjson", last or "浏览器取数失败")


def _try_relays(url, timeout):
    for name, mk in RELAYS:
        try:
            t0 = time.time()
            d = _fetch_once(mk(url), timeout)
            if isinstance(d, dict) and ("results" in d or "events" in d or "statistics" in d or "home" in d):
                print("  · 通过中转 %s 取数成功（%.1fs）" % (name, time.time() - t0))
                return d
        except Exception:
            continue
    return None


def diag():
    """返回一组诊断结果，用于在页面/控制台解释『为什么连不上』。"""
    checks = []

    def add(name, ok, detail, hint=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail), "hint": hint})

    px = proxy_url()
    add("代理设置", True, px if px else "未设置（直连）",
        "如果直连不通，可以在同目录放一个 proxy.txt，里面写一行代理地址，例如 http://127.0.0.1:7890")

    for host in API_HOSTS:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            ips = sorted({i[4][0] for i in infos})
            add("DNS %s" % host, True, "、".join(ips[:3]))
        except Exception as e:
            add("DNS %s" % host, False, "%s: %s" % (type(e).__name__, e), HINT["dns"])

    for host in API_HOSTS:
        t0 = time.time()
        try:
            sk = socket.create_connection((host, 443), timeout=6)
            sk.close()
            add("连通 %s:443" % host, True, "%.2f 秒" % (time.time() - t0))
        except Exception as e:
            add("连通 %s:443" % host, False, "%s: %s" % (type(e).__name__, e), HINT["timeout"])
            continue
        t0 = time.time()
        try:
            try:
                d = _fetch_once("https://%s/api/v1/search/all?q=arsenal" % host, 8)
            except NetError as e1:
                if e1.kind != "tls":
                    raise
                d = _fetch_once("https://%s/api/v1/search/all?q=arsenal" % host, 8, ctx=_ctx_no_verify())
            add("直连取数 %s" % host, True, "%.2f 秒，返回 %d 条" % (time.time() - t0, len(d.get("results") or [])))
        except NetError as e:
            add("直连取数 %s" % host, False, e.msg, HINT.get(e.kind, ""))

    if not [c for c in checks if c["ok"] and c["name"].startswith("直连取数 ")]:
        try:
            d2 = _fetch_via_curl("https://%s/api/v1/search/all?q=arsenal" % API_HOSTS[0], 10)
            add("curl 引擎", True, "可用（返回 %d 条，程序会自动改走它）" % len(d2.get("results") or []))
        except Exception as e:
            add("curl 引擎", False, str(e)[:80], "curl 指纹也像脚本，被拦正常，看下面两项。")
        try:
            d3 = _fetch_via_curl_cffi("https://%s/api/v1/search/all?q=arsenal" % API_HOSTS[0], 15)
            add("curl_cffi 指纹", True, "可用（返回 %d 条，会自动优先用它）" % len(d3.get("results") or []))
        except NetError as e:
            why = "未安装：双击目录里的「安装依赖.bat」" if "未安装" in str(e) else str(e)[:60]
            add("curl_cffi 指纹", False, why, "装上它最省事；装不了就看下面那行浏览器引擎。")
        try:
            d4 = _fetch_via_browser("https://%s/api/v1/search/all?q=arsenal" % API_HOSTS[0], 35)
            add("本机浏览器引擎", True, "可用（%s，会用它取数）" % os.path.basename(browser_exe() or ""))
        except NetError as e:
            add("本机浏览器引擎", False, str(e)[:70], "浏览器方式也失败，只能挂代理了。")

        try:
            d = _try_relays("https://%s/api/v1/search/all?q=arsenal" % API_HOSTS[0], 12)
            if d is not None:
                add("公共中转", True, "可用（直连不通时会自动改走中转取数）")
            else:
                add("公共中转", False, "也不通", "中转站点在本机网络同样连不上，需要挂代理。")
        except Exception as e:
            add("公共中转", False, str(e)[:80], "")

    good = [c for c in checks if c["ok"] and (c["name"].startswith("直连取数 ") or c["name"] in ("公共中转", "curl_cffi 指纹", "本机浏览器引擎"))]
    # 直连、curl、curl_cffi 三路都 403 → 是 IP/出口被封，不是指纹问题，只能走代理或换网络
    e403 = [c for c in checks if c["name"].startswith("直连取数 ") or c["name"] in ("curl 引擎", "curl_cffi 指纹")]
    if not good and e403 and all("403" in c["detail"] for c in e403):
        return {"ok": False, "checks": checks,
                "verdict": "你的网络出口被 Cloudflare 拦了（连伪装成 Chrome 的 curl_cffi 也 403，说明不是指纹问题是 IP）。"
                           "在下面填一个代理（Clash/v2ray 的 HTTP 端口，例如 http://127.0.0.1:7890）再重测；"
                           "实在没有代理，就用手机开热点换一条线路试试。",
                "proxy": px or "", "python": sys.version.split()[0]}
    bad = [c for c in checks if not c["ok"]]
    if good:
        verdict = ("可以正常取数（%s）。如果页面仍报错，多半是刚才那一下被限流，重试即可。"
                   % good[0]["name"])
    elif bad:
        verdict = "取数失败：" + "；".join(c["hint"] or c["detail"] for c in bad[:2])
    else:
        verdict = "未完成检测。"
    return {"ok": bool(good), "checks": checks, "verdict": verdict,
            "proxy": px or "", "python": sys.version.split()[0]}


CACHE_VER = "v3_"   # 解析逻辑改过就换版本号，旧缓存自然失效


def cached(key, fn, ttl=CACHE_TTL):
    key = CACHE_VER + key
    path = os.path.join(CACHE_DIR, key + ".json")
    try:
        if time.time() - os.path.getmtime(path) < ttl:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    data = fn()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
    return data


def safe(key, fn, default=None):
    """任何一路失败都不让整个页面挂掉。"""
    try:
        return cached(key, fn)
    except Exception as e:
        print("  ! %s -> %s" % (key, e))
        return default


# ---------------------------------------------------------------- 解析
def _items(event_json):
    """把统计里的所有 statisticsItems 摊平成 {key: item}（只取全场 ALL）。"""
    out = {}
    for block in event_json.get("statistics", []):
        if block.get("period") != "ALL":
            continue
        for grp in block.get("groups", []):
            for it in grp.get("statisticsItems", []):
                k = it.get("key")
                if k and k not in out:
                    out[k] = it
    return out


def _num(item, side):
    if not item:
        return None
    v = item.get("homeValue" if side == "home" else "awayValue")
    return v


def parse_stats(event_json):
    it = _items(event_json)
    g = lambda key, side: _num(it.get(key), side)
    return {
        "bcH": g("bigChanceCreated", "home"), "bcA": g("bigChanceCreated", "away"),
        "bcmH": g("bigChanceMissed", "home"), "bcmA": g("bigChanceMissed", "away"),
        "bcsH": g("bigChanceScored", "home"), "bcsA": g("bigChanceScored", "away"),
        "xgH": g("expectedGoals", "home"), "xgA": g("expectedGoals", "away"),
        "posH": g("ballPossession", "home"), "posA": g("ballPossession", "away"),
        "shH": g("totalShotsOnGoal", "home"), "shA": g("totalShotsOnGoal", "away"),
        "sotH": g("shotsOnGoal", "home"), "sotA": g("shotsOnGoal", "away"),
        "corH": g("cornerKicks", "home"), "corA": g("cornerKicks", "away"),
        "rateH": g("avgRating", "home"), "rateA": g("avgRating", "away"),
    }


def parse_players(lineups, side):
    """side: home/away -> [{name, rating, minutes, sub, pos, shirt}]"""
    block = (lineups or {}).get(side) or {}
    out = []
    for p in block.get("players") or []:
        pl = p.get("player") or {}
        st = p.get("statistics") or {}
        rating = st.get("rating")
        mins = st.get("minutesPlayed")
        out.append({
            "name": pl.get("shortName") or pl.get("name") or "?",
            "full": pl.get("name") or "",
            "rating": round(float(rating), 1) if isinstance(rating, (int, float)) else None,
            "minutes": mins if isinstance(mins, (int, float)) else None,
            "sub": bool(p.get("substitute")),
            "pos": p.get("position") or "",
            "shirt": p.get("shirtNumber"),
            "cap": bool(p.get("captain")),
        })
    # 首发按位置、替补按评分
    out.sort(key=lambda x: (x["sub"], x["pos"] not in ("G",), -(x["rating"] or 0)))
    return out


def fmt_date(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else ""


def build_match(ev, team_id, with_players=True):
    eid = ev["id"]
    home_id = (ev.get("homeTeam") or {}).get("id")
    side = "home" if home_id == team_id else "away"
    opp_side = "away" if side == "home" else "home"

    st = safe("stats_%s" % eid, lambda: http_json("%s/event/%s/statistics" % (API, eid), timeout=10, retries=0), {})
    st = parse_stats(st or {})

    hs = (ev.get("homeScore") or {}).get("current")
    as_ = (ev.get("awayScore") or {}).get("current")
    my, op = (hs, as_) if side == "home" else (as_, hs)

    players = []
    if with_players and ev.get("hasEventPlayerStatistics", True):
        lu = safe("lineups_%s" % eid, lambda: http_json("%s/event/%s/lineups" % (API, eid), timeout=10, retries=0), {})
        players = parse_players(lu or {}, side)

    def pick(k_my, k_op):
        return (st.get(k_my), st.get(k_op)) if side == "home" else (st.get(k_op), st.get(k_my))

    bc_my, bc_op = pick("bcH", "bcA")
    bcm_my, bcm_op = pick("bcmH", "bcmA")
    bcs_my, bcs_op = pick("bcsH", "bcsA")
    xg_my, xg_op = pick("xgH", "xgA")
    pos_my, pos_op = pick("posH", "posA")
    sh_my, sh_op = pick("shH", "shA")
    sot_my, sot_op = pick("sotH", "sotA")
    cor_my, cor_op = pick("corH", "corA")
    rt_my, rt_op = pick("rateH", "rateA")

    res = "D"
    if my is not None and op is not None:
        res = "W" if my > op else ("L" if my < op else "D")

    return {
        "id": eid,
        "date": fmt_date(ev.get("startTimestamp")),
        "ts": ev.get("startTimestamp"),
        "comp": ((ev.get("tournament") or {}).get("name") or "").split(",")[0],
        "round": (ev.get("roundInfo") or {}).get("round"),
        "home": (ev.get("homeTeam") or {}).get("name"),
        "away": (ev.get("awayTeam") or {}).get("name"),
        "hs": hs, "as": as_, "my": my, "op": op, "res": res,
        "venue": "主" if side == "home" else "客",
        "opp": (ev.get(opp_side + "Team") or {}).get("name"),
        "opp_id": (ev.get(opp_side + "Team") or {}).get("id"),
        "bc": [bc_my, bc_op], "bcm": [bcm_my, bcm_op], "bcs": [bcs_my, bcs_op],
        "xg": [xg_my, xg_op], "pos": [pos_my, pos_op],
        "shots": [sh_my, sh_op], "sot": [sot_my, sot_op],
        "corner": [cor_my, cor_op], "rate": [rt_my, rt_op],
        "players": players,
    }


def team_report(team_id, n=DEFAULT_N):
    evs = safe("team_%s_events" % team_id,
               lambda: http_json("%s/team/%s/events/last/0" % (API, team_id)), {})
    if not evs or "events" not in evs:
        raise RuntimeError("没拿到这支球队的比赛列表：可能网络不通，或被数据源限流，稍等 1 分钟再试")
    events = (evs or {}).get("events") or []
    done = [e for e in events if (e.get("status") or {}).get("type") == "finished"]
    done.sort(key=lambda e: e.get("startTimestamp") or 0, reverse=True)
    done = done[:n]
    # 浏览器引擎每次要真开一个进程，别一次开六个
    workers = 3 if _PREF["engine"] == "browser" else 6
    with ThreadPoolExecutor(max_workers=workers) as ex:
        matches = list(ex.map(lambda e: build_match(e, team_id), done))

    agg = {"W": 0, "D": 0, "L": 0, "gf": 0, "ga": 0,
           "bc": 0.0, "bcc": 0.0, "bcm": 0.0, "xg": 0.0, "xga": 0.0, "cnt": 0}
    for m in matches:
        agg[m["res"]] += 1
        if m["my"] is not None:
            agg["gf"] += m["my"]
            agg["ga"] += m["op"]
        agg["cnt"] += 1
        if m["bc"][0] is not None:
            agg["bc"] += m["bc"][0]
        if m["bc"][1] is not None:
            agg["bcc"] += m["bc"][1]
        if m["bcm"][0] is not None:
            agg["bcm"] += m["bcm"][0]
        if m["xg"][0] is not None:
            agg["xg"] += m["xg"][0]
        if m["xg"][1] is not None:
            agg["xga"] += m["xg"][1]
    k = max(1, agg["cnt"])
    summary = {
        "W": agg["W"], "D": agg["D"], "L": agg["L"],
        "gf": agg["gf"], "ga": agg["ga"],
        "bc": round(agg["bc"] / k, 2), "bcc": round(agg["bcc"] / k, 2),
        "bcm": round(agg["bcm"] / k, 2),
        "xg": round(agg["xg"] / k, 2), "xga": round(agg["xga"] / k, 2),
        "n": k,
    }
    return {"matches": matches, "summary": summary}


# ---------------------------------------------------------------- HTTP 服务


def pip_install(pkg="curl_cffi", timeout=240):
    """在程序里直接装包，用户不用去双击 bat（那个黑窗口一开就没了）。"""
    import importlib
    base = [sys.executable, "-m", "pip", "install", "--upgrade", pkg,
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]
    logs = []
    for extra in ([], ["--user"]):
        cmd = base + extra
        print("  · 正在安装 %s %s" % (pkg, "（用户目录）" if extra else ""))
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except Exception as e:
            logs.append("启动 pip 失败：%s" % str(e)[:200])
            break
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
        logs.append(out[-1200:])
        if r.returncode == 0:
            importlib.invalidate_caches()
            try:
                import curl_cffi  # noqa: F401
                return True, out[-600:]
            except Exception as e:
                logs.append("装完了但导入失败：%s" % str(e)[:150])
                continue
    return False, " | ".join(logs)[-1800:]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/api/install":
            try:
                ok, log = pip_install("curl_cffi")
            except Exception as e:
                ok, log = False, str(e)[:500]
            try:
                d = diag()
            except Exception:
                d = {}
            return self._send(200, json.dumps(
                {"ok": ok, "log": log, "verdict": d.get("verdict", ""),
                 "engine": _PREF["engine"]}, ensure_ascii=False))

        if u.path == "/api/proxy":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
                px = (body.get("proxy") or "").strip()
                if px:
                    with open(PROXY_FILE, "w", encoding="utf-8") as f:
                        f.write(px + chr(10))
                else:
                    try:
                        os.remove(PROXY_FILE)
                    except Exception:
                        pass
                d = diag()
                return self._send(200, json.dumps(
                    {"saved": px, "ok": d["ok"], "verdict": d["verdict"]}, ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, PAGE, "text/html; charset=utf-8")

            if u.path == "/api/diag":
                try:
                    return self._send(200, json.dumps(diag(), ensure_ascii=False))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))

            if u.path == "/api/search":
                q = (qs.get("q") or [""])[0].strip()
                if not q:
                    return self._send(200, json.dumps({"q": q, "terms": [], "teams": []}, ensure_ascii=False))
                terms = guess_terms(q)
                teams, seen, err = [], set(), None
                for term in terms:
                    try:
                        hit = cached("search_%s" % urllib.parse.quote(term),
                                     lambda t=term: http_json("%s/search/all?q=%s" % (API, urllib.parse.quote(t)),
                                                              timeout=12))
                    except Exception as e:
                        err = e
                        continue
                    if not isinstance(hit, dict) or "results" not in hit:
                        err = NetError("badjson", "搜索接口返回异常内容")
                        continue
                    for r in (hit or {}).get("results") or []:
                        if r.get("type") != "team":
                            continue
                        ent = r.get("entity") or {}
                        if (ent.get("sport") or {}).get("slug") != "football":
                            continue
                        tid = ent.get("id")
                        if tid in seen:
                            continue
                        seen.add(tid)
                        teams.append({
                            "id": tid, "name": ent.get("name"),
                            "country": (ent.get("country") or {}).get("name") or "",
                            "women": ent.get("gender") == "F",
                        })
                        if len(teams) >= 10:
                            break
                    if len(teams) >= 10:
                        break
                # 精确同名、男队排前面，避免 "Arsenal" 先弹出 Arsenal Tula
                kq = norm(q)
                teams.sort(key=lambda t: (0 if norm(t["name"]) == kq else 1,
                                          1 if t["women"] else 0,
                                          len(t["name"])))
                if not teams and err is not None:
                    print("  ! search ->", err)
                    if isinstance(err, NetError):
                        why = HINT.get(err.kind, err.msg)
                    else:
                        why = str(err)[:120]
                    return self._send(500, json.dumps(
                        {"error": "取数失败：" + why + "（点下面的网络诊断可看详细原因）"},
                        ensure_ascii=False))
                return self._send(200, json.dumps(
                    {"q": q, "terms": terms, "teams": teams}, ensure_ascii=False))

            if u.path == "/api/team":
                tid = int((qs.get("id") or ["0"])[0])
                n = int((qs.get("n") or [DEFAULT_N])[0])
                n = max(1, min(10, n))
                zh = (qs.get("zh") or [""])[0].strip()
                nm = (qs.get("name") or [""])[0].strip()
                data = team_report(tid, n)
                if zh and nm:
                    learn(zh, tid, nm)      # 记住这个中文写法，下次直接命中
                return self._send(200, json.dumps(data, ensure_ascii=False))

            if u.path == "/api/teams":
                return self._send(200, json.dumps(
                    [{"id": k, "name": v} for k, v in sorted(ALIAS.items())], ensure_ascii=False))

            return self._send(404, json.dumps({"error": "not found"}))
        except BrokenPipeError:
            return
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1b2d">
<title>球队近况</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0f1b2d;color:#e6edf6;
 font:15px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
 padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
header{position:sticky;top:0;z-index:9;background:#0f1b2d;padding:12px 14px 10px;
 border-bottom:1px solid #21324b}
h1{margin:0 0 10px;font-size:17px;font-weight:700;letter-spacing:.5px}
h1 small{font-weight:400;color:#7f93ad;font-size:12px;margin-left:6px}
.search{display:flex;gap:8px}
input,button{font:inherit;border-radius:10px;border:1px solid #2b4162;background:#16233a;color:#e6edf6}
input{flex:1;padding:12px 13px;min-width:0}
input:focus{outline:none;border-color:#3f6fa8}
button{padding:12px 18px;background:#2f6fd0;border-color:#2f6fd0;color:#fff;font-weight:600}
button:active{background:#2559a8}
button.ghost{background:#16233a;border-color:#2b4162;color:#c9d6e6;font-weight:500;padding:8px 12px;font-size:13px}
.quick{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
main{padding:14px}
.hint{color:#7f93ad;text-align:center;padding:30px 10px;font-size:13.5px;line-height:1.9}
.teamlist{display:flex;flex-direction:column;gap:8px}
.teamitem{padding:13px 14px;background:#16233a;border:1px solid #24344d;border-radius:12px;
 display:flex;justify-content:space-between;align-items:center}
.teamitem:active{background:#1d2e49}
.teamitem .c{color:#7f93ad;font-size:12.5px}
.summary{background:linear-gradient(160deg,#182a44,#141f33);border:1px solid #24344d;
 border-radius:14px;padding:14px;margin-bottom:14px}
.summary .top{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
.summary .nm{font-size:17px;font-weight:700}
.summary .rec{font-size:13px;color:#9fb3cc}
.wdl{display:flex;gap:5px}
.wdl span{width:24px;height:24px;border-radius:6px;display:grid;place-items:center;
 font-size:12px;font-weight:700}
.W{background:#1e6b45;color:#8ff0bd}.D{background:#5a4a1e;color:#f3d98a}.L{background:#6b2530;color:#ff9fae}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.kpi{background:#101c2e;border:1px solid #1e2f49;border-radius:10px;padding:9px 10px}
.kpi b{display:block;font-size:17px;color:#eaf2ff}
.kpi i{font-style:normal;color:#7f93ad;font-size:11.5px}
.card{background:#16233a;border:1px solid #24344d;border-radius:14px;margin-bottom:12px;overflow:hidden}
.card .hd{display:flex;justify-content:space-between;align-items:center;gap:8px;
 padding:11px 13px;background:#1a2942;font-size:12.5px;color:#9fb3cc}
.card .hd .comp{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.res{font-weight:700;padding:2px 8px;border-radius:6px;font-size:12px}
.card .score{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;padding:13px}
.card .score .t{font-size:14.5px;font-weight:600}
.card .score .t.a{text-align:right}
.card .score .s{font-size:21px;font-weight:800;letter-spacing:1px;min-width:66px;text-align:center}
.card .score .t.me{color:#7cc4ff}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 10px;border-top:1px solid #202f47}
th{color:#8ba0ba;font-weight:500;font-size:11.5px;text-align:right;background:#141f33}
td:first-child,th:first-child{text-align:left;color:#9fb3cc}
td.n{text-align:right;font-variant-numeric:tabular-nums}
td.hi{color:#7cc4ff;font-weight:700}
.neg{color:#ff9fae}.pos{color:#8ff0bd}
.players{max-height:0;overflow:hidden;transition:max-height .25s ease}
.players.open{max-height:1400px}
.prow{display:flex;align-items:center;gap:8px;padding:7px 12px;border-top:1px solid #202f47;font-size:13px}
.prow .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prow .tag{font-size:10.5px;padding:1px 5px;border-radius:4px;background:#243a58;color:#9fb3cc}
.prow .tag.sub{background:#3a2f1e;color:#e8c98a}
.prow .min{color:#7f93ad;font-size:11.5px;width:38px;text-align:right}
.rt{font-weight:700;width:38px;text-align:right;font-variant-numeric:tabular-nums}
.rt.g{color:#8ff0bd}.rt.y{color:#f3d98a}.rt.r{color:#ff9fae}
.toggle{width:100%;padding:10px;background:#141f33;border:0;border-top:1px solid #202f47;
 color:#8ba0ba;font-size:12.5px;border-radius:0}
footer{color:#5f728c;text-align:center;font-size:11.5px;padding:14px 16px 26px;line-height:1.8}
.spin{display:inline-block;width:14px;height:14px;border:2px solid #3f6fa8;
 border-right-color:transparent;border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px}
@keyframes sp{to{transform:rotate(360deg)}}
.dbox{padding:14px 16px 8px}
.dtitle{font-size:14px;font-weight:700;line-height:1.6;margin-bottom:12px;padding:10px 12px;border-radius:8px}
.dtitle.ok{background:#12352a;color:#8ff0bd}
.dtitle.bad{background:#3a1f26;color:#ffb3be}
.drow{position:relative;padding:8px 0 8px 18px;border-bottom:1px solid #1e2c42;font-size:13px}
.dot{position:absolute;left:2px;top:13px;width:8px;height:8px;border-radius:50%}
.dot.ok{background:#3ddc97}.dot.bad{background:#ff7a8a}
.dn{color:#cfe0f5;font-weight:600;margin-right:8px}
.dd{color:#8ba0ba;font-size:12px}
.dh{color:#e2b06a;font-size:12px;line-height:1.6;margin-top:4px}
.plog{white-space:pre-wrap;word-break:break-all;font-size:12px;line-height:1.5;color:#9fb0c9;background:#0b1526;padding:10px;border-radius:8px;margin-top:10px;max-height:46vh;overflow:auto}.dfoot{color:#5f728c;font-size:11.5px;padding:14px 0 18px}
.dpx{padding:14px 0 4px;border-top:1px solid #1e2c42;margin-top:6px}
.dpx input{width:60%;background:#0e1726;border:1px solid #2b4162;color:#cfe0f5;padding:9px 10px;border-radius:8px;font-size:13px}
</style></head><body>
<header>
  <h1>球队近况 <small>最近 N 场 · 绝佳机会 · 球员评分</small></h1>
  <div class="search">
    <input id="q" placeholder="球队名，中文或英文（阿森纳 / Arsenal）" autocomplete="off" enterkeyhint="search">
    <button id="go">查询</button>
  </div>
  <div class="quick" id="quick"></div>
  <div class="quick" id="nsel">
    <button class="ghost" data-n="5">近 5 场</button>
    <button class="ghost" data-n="10">近 10 场</button>
  </div>
</header>
<main id="main">
  <div class="hint">输入球队名开始。<br>中文名可以直接搜（阿森纳、利物浦、拜仁、矿工…）</div>
</main>
<footer>数据来自 Sofascore 公开接口，仅供个人查看<br>绝佳机会 = Big chances，错失 = Big chances missed<br>
  <button id="diag" class="ghost" style="margin-top:10px">网络诊断</button></footer>
<script>
const $ = s => document.querySelector(s);
const main = $('#main');
let N = 5;

let LAST = null;
const QUICK = ['阿森纳','利物浦','曼城','曼联','切尔西','皇马','巴萨','拜仁','国米','巴黎'];
$('#quick').innerHTML = QUICK.map(t => `<button class="ghost" data-t="${t}">${t}</button>`).join('');
$('#quick').onclick = e => {
  const t = e.target.dataset.t;
  if (t) { $('#q').value = t; doSearch(); }
};

$('#nsel').onclick = e => {
  const n = e.target.dataset.n;
  if (!n) return;
  N = Number(n);
  [...$('#nsel').children].forEach(b => b.style.borderColor = (Number(b.dataset.n)===N) ? '#2f6fd0' : '#2b4162');
  if (LAST) loadTeam(LAST.id, LAST.name, LAST.zh);
};

$('#diag').onclick = showDiag;
$('#go').onclick = doSearch;
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
[...$('#nsel').children].forEach(b => b.style.borderColor = (Number(b.dataset.n)===N) ? '#2f6fd0' : '#2b4162');

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function num(v,d=0){ if(v==null||v==='') return '—'; return (Math.round(v*Math.pow(10,d))/Math.pow(10,d)).toFixed(d); }
function rateClass(r){ if(r==null) return ''; return r>=7.5?'g':(r>=6.5?'y':'r'); }

async function doSearch(){
  const q = $('#q').value.trim();
  if(!q) return;
  main.innerHTML = '<div class="hint"><span class="spin"></span> 搜索中…</div>';
  try{
    const r = await fetch('/api/search?q=' + encodeURIComponent(q));
    const d = await r.json();
    if(!r.ok){ main.innerHTML = '<div class="hint">' + esc(d.error || '搜索失败')
      + '<br><br><button class="ghost" onclick="showDiag()">点这里做网络诊断</button></div>'; return; }
    const list = d.teams || [];
    if(!list.length){
      main.innerHTML = '<div class="hint">没找到「' + esc(q) + '」这支球队。<br>'
        + '试试英文写法（Arsenal / Bayern Munich），或者只写队名的主体部分。</div>';
      return;
    }
    if(list.length === 1) return loadTeam(list[0].id, list[0].name, q);
    main.innerHTML = '<div class="hint" style="text-align:left;padding:14px 16px">找到 ' + list.length
      + ' 支球队，点一个继续（会记住你的叫法）：</div>'
      + '<div class="teamlist">' + list.map(t =>
      `<div class="teamitem" data-id="${t.id}" data-nm="${esc(t.name)}">
         <div>${esc(t.name)}${t.women?' <span class="c">(女足)</span>':''}</div>
         <div class="c">${esc(t.country)} ›</div>
       </div>`).join('') + '</div>';
    main.querySelectorAll('.teamitem').forEach(el => {
      el.onclick = () => loadTeam(el.dataset.id, el.dataset.nm, q);
    });
  }catch(e){
    main.innerHTML = '<div class="hint">出错：' + esc(e.message) + '</div>';
  }
}

async function showDiag(){
  main.innerHTML = '<div class="hint"><span class="spin"></span> 正在检测网络…（最多 30 秒）</div>';
  try{
    const r = await fetch('/api/diag');
    const d = await r.json();
    const rows = (d.checks||[]).map(c => `
      <div class="drow">
        <span class="dot ${c.ok?'ok':'bad'}"></span>
        <span class="dn">${esc(c.name)}</span>
        <span class="dd">${esc(c.detail)}</span>
        ${c.hint && !c.ok ? `<div class="dh">${esc(c.hint)}</div>` : ''}
      </div>`).join('');
    main.innerHTML = `<div class="dbox"><div class="dtitle ${d.ok?'ok':'bad'}">${esc(d.verdict)}</div>
      ${rows}
      <div class="dpx">
        <div class="dh" style="margin-bottom:6px">代理设置（填 Clash/v2ray 的 HTTP 端口，例如 http://127.0.0.1:7890；留空=直连）</div>
        <input id="pxin" value="${esc(d.proxy||'')}" placeholder="http://127.0.0.1:7890">
        <button id="pxsave" class="ghost" style="margin-left:8px">保存并重测</button>
        ${(d.checks||[]).some(c => c.name === 'curl_cffi 指纹' && !c.ok)
          ? '<button id="pxinst" class="ghost" style="margin-left:8px">一键安装 curl_cffi</button>' : ''}
      </div>
      <div class="dfoot">Python ${esc(d.python||'')}</div></div>`;
    const bi = $('#pxinst');
    if(bi) bi.onclick = async () => {
      main.innerHTML = '<div class="hint"><span class="spin"></span> 正在安装 curl_cffi（走清华镜像，约 30 秒）…</div>';
      try{
        const rr = await fetch('/api/install', {method:'POST'});
        const dd = await rr.json();
        if(!dd.ok){
          main.innerHTML = `<div class="dbox"><div class="dtitle bad">安装失败（可以把下面这段发我）</div>
            <pre class="plog">${esc(dd.log||'')}</pre>
            <button id="pxback" class="ghost" style="margin-top:10px">返回诊断</button></div>`;
          $('#pxback').onclick = () => showDiag();
          return;
        }
        await showDiag();
      }catch(e){ main.innerHTML = '<div class="hint">安装出错：' + esc(e.message) + '</div>'; }
    };
    $('#pxsave').onclick = async () => {
      const v = $('#pxin').value.trim();
      main.innerHTML = '<div class="hint"><span class="spin"></span> 保存中并重新检测…（最多 40 秒）</div>';
      try{
        const r2 = await fetch('/api/proxy', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({proxy: v})});
        const d2 = await r2.json();
        if(!r2.ok) throw new Error(d2.error||'保存失败');
        await showDiag();
      }catch(e){ main.innerHTML = '<div class="hint">出错：' + esc(e.message) + '</div>'; }
    };
  }catch(e){
    main.innerHTML = '<div class="hint">诊断接口出错：' + esc(e.message) + '</div>';
  }
}

async function loadTeam(id, name, zh){
  LAST = {id, name, zh: zh || ''};
  const tip = (zh && zh.toLowerCase() !== String(name).toLowerCase())
    ? `（你搜的是「${esc(zh)}」）` : '';
  main.innerHTML = `<div class="hint"><span class="spin"></span> 加载 ${esc(name)} ${tip} 最近 ${N} 场…<br><span style="font-size:12px">首次需要拉取每场统计和阵容，约 5-15 秒</span></div>`;
  try{
    let url = `/api/team?id=${id}&n=${N}`;
    if(LAST.zh) url += '&zh=' + encodeURIComponent(LAST.zh) + '&name=' + encodeURIComponent(name);
    const r = await fetch(url);
    const d = await r.json();
    if(!r.ok){ throw new Error(d.error || '加载失败'); }
    render(d, name);
  }catch(e){
    main.innerHTML = '<div class="hint">出错：' + esc(e.message) + '</div>';
  }
}

function render(d, name){
  const s = d.summary, ms = d.matches;
  if(!ms.length){ main.innerHTML = '<div class="hint">这支球队没有已结束的比赛</div>'; return; }
  const wdl = ms.map(m => `<span class="${m.res}">${m.res==='W'?'胜':(m.res==='D'?'平':'负')}</span>`).join('');
  let html = `<div class="summary">
    <div class="top"><div class="nm">${esc(name)}</div>
      <div class="rec">近${s.n}场 ${s.W}胜${s.D}平${s.L}负 · ${s.gf}:${s.ga}</div></div>
    <div class="wdl">${wdl}</div>
    <div class="grid">
      <div class="kpi"><b>${num(s.bc,1)}</b><i>场均绝佳机会</i></div>
      <div class="kpi"><b>${num(s.bcc,1)}</b><i>场均被创造</i></div>
      <div class="kpi"><b>${num(s.bcm,1)}</b><i>场均错失</i></div>
      <div class="kpi"><b>${num(s.xg,2)}</b><i>场均 xG</i></div>
      <div class="kpi"><b>${num(s.xga,2)}</b><i>场均 xGA</i></div>
      <div class="kpi"><b>${s.W*3+s.D}</b><i>近${s.n}场积分</i></div>
    </div></div>`;

  html += ms.map((m,i) => {
    const win = m.res === 'W', lose = m.res === 'L';
    const resCls = m.res, resTxt = win?'胜':(lose?'负':'平');
    const homeMe = m.venue === '主';
    const rows = [
      ['绝佳机会', m.bc, 1, true],
      ['错失绝佳机会', m.bcm, 1, false],
      ['xG', m.xg, 2, true],
      ['射正 / 射门', [m.sot[0]==null?null:m.sot[0]+' / '+m.shots[0], m.sot[1]==null?null:m.sot[1]+' / '+m.shots[1]], 0, false],
      ['控球率 %', m.pos, 0, false],
      ['角球', m.corner, 0, false],
      ['全队平均评分', m.rate, 1, false],
    ];
    const tbl = `<table>
      <tr><th></th><th>${esc(homeMe?'本队':'对手')}</th><th>${esc(homeMe?'对手':'本队')}</th></tr>
      <tr><td>比分</td>
          <td class="n ${homeMe?'hi':''}">${m.hs ?? '—'}</td>
          <td class="n ${homeMe?'':'hi'}">${m.as ?? '—'}</td></tr>
      ${rows.map(r => {
        const a = r[1][0], b = r[1][1];
        const fx = v => (v==null) ? '—' : (typeof v === 'number' ? num(v, r[2]) : v);
        return `<tr><td>${r[0]}</td>
          <td class="n">${fx(a)}</td><td class="n">${fx(b)}</td></tr>`;
      }).join('')}
    </table>`;

    const pl = m.players || [];
    const starters = pl.filter(p => !p.sub);
    const subs = pl.filter(p => p.sub);
    const prow = p => `<div class="prow">
        <span class="tag${p.sub?' sub':''}">${p.sub?'替':'首'}</span>
        <span class="nm">${esc(p.name)}${p.cap?' (C)':''}</span>
        <span class="min">${p.minutes===0?'未上':(p.minutes==null?'':p.minutes+"'")}</span>
        <span class="rt ${rateClass(p.rating)}">${p.rating==null?'—':p.rating.toFixed(1)}</span>
      </div>`;
    const plHtml = pl.length ? `
      <button class="toggle" data-i="${i}">球员评分与上场 ▾ (${starters.length} 首发 / ${subs.filter(s=>s.minutes>0).length} 替补登场)</button><div class="players" id="pl${i}">
        ${starters.map(prow).join('')}
        ${subs.length?`<div class="prow" style="background:#141f33;color:#8ba0ba;font-size:11.5px">替补席</div>`+subs.map(prow).join(''):''}
      </div>` : '';

    return `<div class="card">
      <div class="hd">
        <span class="comp">${esc(m.comp)}${m.round?' · 第'+m.round+'轮':''}</span>
        <span><span style="color:#6f849e;font-size:11.5px;margin-right:8px">${esc(m.date)} · ${m.venue}场</span>
        <span class="res ${resCls}">${resTxt}</span></span>
      </div>
      <div class="score">
        <div class="t ${homeMe?'me':''} a" style="text-align:right">${esc(m.home)}</div>
        <div class="s">${m.hs ?? '—'} : ${m.as ?? '—'}</div>
        <div class="t ${homeMe?'':'me'}">${esc(m.away)}</div>
      </div>
      ${tbl}${plHtml}
    </div>`;
  }).join('');

  main.innerHTML = html;
  main.querySelectorAll('.toggle').forEach(b => {
    b.onclick = () => {
      const box = document.getElementById('pl' + b.dataset.i);
      const open = box.classList.toggle('open');
      b.dataset.lbl = b.dataset.lbl || b.textContent.replace('▾', '').trim();
      b.textContent = (open ? '▲ 收起' : '▼ ' + b.dataset.lbl);
    };
  });
}

const p = new URLSearchParams(location.search).get('q');
if (p) { $('#q').value = p; doSearch(); }
</script></body></html>"""


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    port = int(os.environ.get("PORT", "8000") or 8000)
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    cloud = bool(os.environ.get("PORT"))
    srv = None
    for p in range(port, port + 12):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print("端口都被占用，换个端口：python app.py 8100")
        return
    ip = lan_ip()
    print("=" * 52)
    print(" 球队近况 已启动")
    if cloud:
        print(" 云端模式，端口 %d（平台分配）" % port)
    else:
        print(" 电脑上打开：   http://127.0.0.1:%d" % port)
        print(" 手机上打开：   http://%s:%d" % (ip, port))
        print(" （手机需与这台电脑连同一个 WiFi）")
        print(" 关闭窗口或按 Ctrl+C 停止")
    print("=" * 52)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
