#!/usr/bin/env python3
"""人形机器人每日资讯 — GitHub Actions 版 V2.2（跨天去重）
多渠道搜索：搜狗新闻 + 搜狗微信 + Bing国际 + 百度资讯 + Google新闻 + RSS科技站
所有标题均带可点击超链接，每条标注来源渠道。
V2.2: 跨天去重 — 已发送过的资讯7天内不再重复推送。
"""

import os
import sys
import re
import json
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ============ 配置 ============
SENDER = "eric_wei@atop-ks.com"
PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECIPIENT = "summer_sun@atop-ks.com"
SMTP_SERVER = "smtp.feishu.cn"
SMTP_PORT = 465

# 跨天去重缓存
SENT_CACHE_FILE = "sent_articles.json"   # 已发送文章哈希缓存（存在仓库根目录）
CACHE_MAX_DAYS = 7                        # 7天内的已发文章不再重复推送

if not PASSWORD:
    print("❌ 未设置 SMTP_PASSWORD 环境变量")
    sys.exit(1)

cst = timezone(timedelta(hours=8))
today = datetime.now(cst).strftime("%Y年%m月%d日")
today_iso = datetime.now(cst).strftime("%Y-%m-%d")


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return s


# ============ 跨天去重缓存 ============
def load_sent_cache():
    """加载已发送文章缓存，自动清理超过 CACHE_MAX_DAYS 的旧记录。
    返回 {hash: date_str} 字典。"""
    if not os.path.exists(SENT_CACHE_FILE):
        return {}
    try:
        with open(SENT_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        hashes = data.get("hashes", {})
        # 清理过期记录
        cutoff = (datetime.now(cst) - timedelta(days=CACHE_MAX_DAYS)).strftime("%Y-%m-%d")
        fresh = {h: d for h, d in hashes.items() if d >= cutoff}
        if len(fresh) < len(hashes):
            print(f"🧹 清理过期缓存: {len(hashes) - len(fresh)} 条（>{CACHE_MAX_DAYS}天）")
        return fresh
    except Exception as e:
        print(f"⚠ 加载缓存失败: {e}，视为空缓存")
        return {}


def save_sent_cache(cache):
    """保存已发送文章缓存到 JSON 文件。"""
    try:
        with open(SENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"hashes": cache}, f, ensure_ascii=False, indent=2)
        print(f"💾 缓存已更新: {len(cache)} 条已发送记录")
    except Exception as e:
        print(f"⚠ 保存缓存失败: {e}")


def compute_hash(title):
    """计算文章标题的 MD5 哈希（去标点、取前40字符）"""
    key = re.sub(r"[【】\[\]「」""'' \-—|｜]", "", title)[:40]
    return hashlib.md5(key.encode()).hexdigest()


def update_sent_cache(news_items):
    """将新发送的文章哈希写入缓存，返回更新后的缓存。"""
    cache = load_sent_cache()
    added = 0
    for title, url, source in news_items:
        h = compute_hash(title)
        if h not in cache:
            cache[h] = today_iso
            added += 1
    print(f"📝 新增 {added} 条到缓存（总计 {len(cache)} 条）")
    save_sent_cache(cache)
    return cache


# ============ 渠道 1: 搜狗新闻 ============
def search_sogou(session):
    queries = [
        "人形机器人 融资 量产",
        "人形机器人 技术突破 发布",
        "人形机器人 特斯拉 优必选 宇树",
        "人形机器人 核心零部件 关节 电机 传感器",
        "具身智能 人形机器人 应用 落地",
        "人形机器人 政策 产业 规划",
    ]
    results = []
    for q in queries:
        try:
            url = f"https://news.sogou.com/news?query={quote(q)}&page=1"
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            for t in soup.select("h3 a"):
                text = t.get_text(strip=True)
                href = t.get("href", "")
                if text and len(text) > 5:
                    results.append((text, href, "搜狗新闻"))
        except Exception as e:
            print(f"  ⚠ 搜狗 '{q[:20]}' 出错: {e}")
    return results


# ============ 渠道 2: 搜狗微信 ============
def search_sogou_weixin(session):
    queries = ["人形机器人", "具身智能", "人形机器人 量产"]
    results = []
    for q in queries:
        try:
            url = f"https://weixin.sogou.com/weixin?type=2&query={quote(q)}"
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.select("h3 a, .txt-box h3 a, .news-list2 li h3 a"):
                text = el.get_text(strip=True)
                href = el.get("href", "")
                if text and len(text) > 5:
                    if href.startswith("/"):
                        href = "https://weixin.sogou.com" + href
                    results.append((text, href, "微信公众号"))
            for el in soup.select("a[href*='mp.weixin.qq.com']"):
                text = el.get_text(strip=True)
                href = el.get("href", "")
                if text and len(text) > 8 and "微信" not in text:
                    results.append((text, href, "微信公众号"))
        except Exception as e:
            print(f"  ⚠ 微信 '{q}' 出错: {e}")
    return results


# ============ 渠道 3: Bing ============
def search_bing(session):
    queries = [
        "humanoid robot 2025 2026",
        "人形机器人 site:cn",
        "humanoid robot Tesla Boston Dynamics",
        "humanoid robot funding mass production",
    ]
    results = []
    for q in queries:
        for bing_url in [
            f"https://www.bing.com/news/search?q={quote(q)}&qft=interval%3d%227%22&FORM=NWRFSH",
            f"https://www.bing.com/search?q={quote(q)}&count=15",
        ]:
            try:
                resp = session.get(bing_url, timeout=20)
                soup = BeautifulSoup(resp.text, "html.parser")
                found = 0
                for el in soup.select(".news-card-body h2 a, .news-card .title a, a[target='_blank'] h2"):
                    text = el.get_text(strip=True)
                    if el.name == "a":
                        href = el.get("href", "")
                    else:
                        pa = el.find_parent("a")
                        href = pa.get("href", "") if pa else ""
                    if text and len(text) > 8 and not text.startswith("https://"):
                        results.append((text, href, "Bing"))
                        found += 1
                for el in soup.select("li.b_algo h2 a, h2 a[href]"):
                    text = el.get_text(strip=True)
                    href = el.get("href", "") if el.name == "a" else ""
                    if text and len(text) > 8 and not text.startswith("https://"):
                        results.append((text, href, "Bing"))
                        found += 1
                if found > 0:
                    break
            except Exception as e:
                print(f"  ⚠ Bing '{q[:20]}': {e}")
    return results


# ============ 渠道 4: 百度资讯 ============
def search_baidu_news(session):
    queries = ["人形机器人", "具身智能", "人形机器人 产业链"]
    results = []
    for q in queries:
        try:
            url = f"https://www.baidu.com/s?rtt=1&bsst=1&cl=2&tn=news&word={quote(q)}"
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            found = 0
            for a in soup.find_all("a"):
                text = a.get_text(strip=True)
                href = a.get("href", "")
                if len(text) > 8 and any(
                    kw in text for kw in ["机器人", "具身", "智能", "AI", "融资", "量产", "关节", "电机"]
                ):
                    results.append((text, href, "百度资讯"))
                    found += 1
                if found >= 15:
                    break
        except Exception as e:
            print(f"  ⚠ 百度 '{q}' 出错: {e}")
    return results


# ============ 渠道 5: Google News RSS ============
def search_google_news(session):
    queries = ["人形机器人", "humanoid robot"]
    results = []
    for q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={quote(q)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
            resp = session.get(url, timeout=20)
            items = re.findall(r'<item>(.+?)</item>', resp.text, re.DOTALL)
            for item in items:
                title_m = re.search(r'<title>(.+?)</title>', item)
                link_m = re.search(r'<link>(.+?)</link>', item)
                if title_m:
                    t = title_m.group(1).strip()
                    link = link_m.group(1).strip() if link_m else ""
                    if len(t) > 8 and t not in ("Google News", "Google 新闻"):
                        results.append((t, link, "Google新闻"))
        except Exception as e:
            print(f"  ⚠ Google News '{q}' 出错: {e}")
    return results


# ============ 渠道 6: RSS 科技站 ============
def search_rss():
    feeds = [
        ("https://www.ithome.com/rss/", "IT之家"),
        ("https://www.mydrivers.com/rss.aspx", "快科技"),
    ]
    results = []
    for feed_url, source in feeds:
        try:
            resp = requests.get(feed_url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"
            })
            items = re.findall(r'<item>(.+?)</item>', resp.text, re.DOTALL)
            for item in items:
                title_m = re.search(r'<title>(.+?)</title>', item)
                link_m = re.search(r'<link>(.+?)</link>', item)
                if title_m:
                    t = title_m.group(1).strip()
                    link = link_m.group(1).strip() if link_m else ""
                    if t in ("IT之家", "快科技"):
                        continue
                    if len(t) > 8 and any(
                        kw in t for kw in ["机器人", "具身", "智能", "AI", "人形",
                                             "Figure", "Tesla", "Optimus", "宇树", "优必选"]
                    ):
                        results.append((t, link, source))
        except Exception as e:
            print(f"  ⚠ RSS {source} 出错: {e}")
    return results


# ============ 去重（含跨天去重） ============
def deduplicate(items, sent_cache=None):
    """按标题去重：本次内去重 + 跨天去重（过滤已发送过的）。
    返回 (title, url, source) 列表，以及被跨天过滤的数量。"""
    if sent_cache is None:
        sent_cache = {}
    seen = set()
    clean = []
    skipped_cross_day = 0
    for title, url, source in items:
        h = compute_hash(title)
        # 跨天去重：已在缓存中的跳过
        if h in sent_cache:
            skipped_cross_day += 1
            continue
        # 本次内去重
        if h not in seen:
            seen.add(h)
            clean.append((title, url, source))
    return clean, skipped_cross_day


# ============ 主流程 ============
def search_all():
    session = make_session()
    all_items = []

    channels = [
        ("搜狗新闻", lambda: search_sogou(session)),
        ("搜狗微信", lambda: search_sogou_weixin(session)),
        ("Bing国际", lambda: search_bing(session)),
        ("百度资讯", lambda: search_baidu_news(session)),
        ("Google新闻", lambda: search_google_news(session)),
        ("RSS科技站", search_rss),
    ]

    for i, (name, fn) in enumerate(channels, 1):
        print(f"\n{'='*50}")
        print(f"🔍 [{i}/{len(channels)}] {name}...")
        try:
            items = fn()
            print(f"       → {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            print(f"       → ❌ 异常: {e}")

    print(f"\n{'='*50}")
    print(f"📊 原始共 {len(all_items)} 条")
    return all_items


def compose_email(news_items):
    """生成 HTML 邮件 — 所有标题带超链接 + 来源标注"""
    categories = {
        "🔥 融资收购": [],
        "🏭 量产与产业": [],
        "🔬 技术突破": [],
        "⚙️ 核心零部件": [],
        "📊 行业动态": [],
    }

    keywords_map = {
        "🔥 融资收购": ["融资", "IPO", "轮", "亿元", "美元", "投资", "估值", "收购", "募资"],
        "🏭 量产与产业": ["量产", "产量", "万台", "产业", "工信部", "落地", "规模", "工厂", "产线", "供应链", "政策"],
        "🔬 技术突破": ["发布", "Nature", "手术", "突破", "新品", "平台", "算法", "AI", "大模型", "大脑", "灵巧手"],
        "⚙️ 核心零部件": ["关节", "电机", "传感器", "减速器", "丝杠", "编码器", "六维力", "驱动", "芯片", "电池"],
    }

    assigned = set()
    for cat, keywords in keywords_map.items():
        for idx, (title, url, source) in enumerate(news_items):
            if idx in assigned:
                continue
            if not keywords or any(kw in title for kw in keywords):
                categories[cat].append((title, url, source))
                assigned.add(idx)

    for idx, (title, url, source) in enumerate(news_items):
        if idx not in assigned:
            categories["📊 行业动态"].append((title, url, source))

    sources = {}
    for _, _, src in news_items:
        sources[src] = sources.get(src, 0) + 1
    source_str = " · ".join(f"{k}({v})" for k, v in sorted(sources.items(), key=lambda x: -x[1]))

    html = f"""<html>
<head><meta charset="utf-8"></head>
<body style="font-family: 'Microsoft YaHei', sans-serif; max-width: 720px; margin: 0 auto;">
<h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
&#x1f916; 人形机器人行业日报 — {today}
</h2>
<p style="color: #666; line-height: 1.6;">
来源渠道：{source_str}<br>
共 <b>{len(news_items)}</b> 条资讯 | 6 渠道聚合 | 点击标题直达原文
</p>
"""

    emoji_map = {
        "微信公众号": "📱", "搜狗新闻": "🔍", "Bing": "🌐", "百度资讯": "📰",
        "Google新闻": "📡", "IT之家": "💻", "快科技": "⚡", "网易科技": "📡",
    }

    for cat, items in categories.items():
        if not items:
            continue
        html += f'<h3 style="color: #d93025; margin-top: 20px; border-bottom: 1px solid #eee;">{cat} ({len(items)})</h3><ul>'
        for title, url, source in items:
            em = emoji_map.get(source, "📌")
            if url:
                html += (
                    f'<li style="margin: 8px 0; line-height: 1.5;">'
                    f'<a href="{url}" target="_blank" style="color: #1a0dab; text-decoration: none;">{title}</a>'
                    f' <span style="color:#999;font-size:11px">[{em} {source}]</span>'
                    f'</li>'
                )
            else:
                html += (
                    f'<li style="margin: 8px 0; line-height: 1.5;">{title}'
                    f' <span style="color:#999;font-size:11px">[{em} {source}]</span>'
                    f'</li>'
                )
        html += "</ul>"

    html += f"""
<hr style="border: 1px solid #eee; margin-top: 30px;">
<p style="color: #999; font-size: 12px; line-height: 1.6;">
本邮件由 GitHub Actions 自动运行并发送<br>
搜索渠道：搜狗新闻 · 搜狗微信 · Bing国际 · 百度资讯 · Google新闻 · IT之家/快科技RSS<br>
如有疑问请联系 eric_wei@atop-ks.com
</p>
<p style="color: #999; font-size: 12px; line-height: 1.4;">
--------------------------------------<br>
Eric_Wei | 韋雷雷<br>
昆山市正耀电子科技有限公司<br>
Atop Electronic Technology Co.,Ltd.<br>
Add：江苏省昆山市长江中路198号裕元新天地广场二号楼8楼(邮编:215300)<br>
Tel: 0512-57902627 Fax: 0512-57020727 Mob: 15850340336<br>
Web：www.atop-ks.com
</p>
</body>
</html>
"""
    return html


def send_email(html_content):
    """通过飞书 SMTP 发送"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🤖 人形机器人日报 — {today}"
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.login(SENDER, PASSWORD)
        server.send_message(msg)

    print(f"✅ 邮件发送成功 → {RECIPIENT}")


def main():
    print("🚀 人形机器人每日资讯 V2.2（跨天去重版）\n")

    # 1. 加载跨天去重缓存
    sent_cache = load_sent_cache()
    print(f"📋 已发送缓存: {len(sent_cache)} 条记录（{CACHE_MAX_DAYS}天内）")

    # 2. 搜索
    all_items = search_all()

    # 3. 去重（本次 + 跨天）
    news, skipped = deduplicate(all_items, sent_cache)
    print(f"   本次去重后: {len(news)} 条")
    if skipped > 0:
        print(f"   跨天过滤: {skipped} 条（已发送过）")

    if not news:
        print("⚠ 没有新资讯（全部已发送过），跳过发送")
        return

    # 4. 整理日报
    print("\n📧 整理日报...")
    html = compose_email(news)

    # 5. 发送
    print("📤 发送邮件...")
    send_email(html)

    # 6. 更新跨天缓存
    print("\n📝 更新发送缓存...")
    update_sent_cache(news)


if __name__ == "__main__":
    main()
