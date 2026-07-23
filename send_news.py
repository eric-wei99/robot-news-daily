#!/usr/bin/env python3
"""人形机器人每日资讯 — GitHub Actions 版
多渠道搜索：搜狗新闻 + Bing + 百度资讯，整理日报并邮件发送。
"""

import os
import sys
import re
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# ============ 配置 ============
SENDER = "eric_wei@atop-ks.com"
PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECIPIENT = "summer_sun@atop-ks.com"
SMTP_SERVER = "smtp.feishu.cn"
SMTP_PORT = 465

if not PASSWORD:
    print("❌ 未设置 SMTP_PASSWORD 环境变量")
    sys.exit(1)

# 北京时间
cst = timezone(timedelta(hours=8))
today = datetime.now(cst).strftime("%Y年%m月%d日")


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


def search_sogou(session):
    """搜狗新闻搜索"""
    queries = [
        "人形机器人 融资 量产",
        "人形机器人 技术突破 发布",
        "人形机器人 特斯拉 优必选 宇树",
    ]
    results = []
    for q in queries:
        url = f"https://news.sogou.com/news?query={requests.utils.quote(q)}&page=1"
        try:
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            for t in soup.select("h3 a"):
                text = t.get_text(strip=True)
                if text and len(text) > 5:
                    results.append((text, "搜狗新闻"))
        except Exception as e:
            print(f"  ⚠ 搜狗 '{q}' 出错: {e}")
    return results


def search_bing(session):
    """Bing 搜索（cn.bing.com，从 GitHub Actions 可直连）"""
    queries = [
        "人形机器人 最新进展",
        "humanoid robot 2025 2026",
        "人形机器人 供应链 核心零部件",
    ]
    results = []
    for q in queries:
        url = (
            f"https://cn.bing.com/search?q={requests.utils.quote(q)}"
            "&setlang=zh-cn&cc=cn&count=15"
        )
        try:
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            for li in soup.select("li.b_algo"):
                h2 = li.select_one("h2 a")
                if h2:
                    text = h2.get_text(strip=True)
                    if text and len(text) > 5:
                        results.append((text, "Bing"))
        except Exception as e:
            print(f"  ⚠ Bing '{q}' 出错: {e}")
    return results


def search_baidu_news(session):
    """百度资讯搜索（简化版，仅标题）"""
    queries = [
        "人形机器人",
        "具身智能",
    ]
    results = []
    for q in queries:
        try:
            # 百度资讯 RSS 接口
            url = (
                f"https://www.baidu.com/s?rtt=1&bsst=1&cl=2&tn=news"
                f"&word={requests.utils.quote(q)}"
            )
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.select("h3.c-title a, h3.news-title_1YtI1 a"):
                text = el.get_text(strip=True)
                if text and len(text) > 5:
                    results.append((text, "百度资讯"))
            # 备用选择器
            if not results:
                for el in soup.select("a[href*='baidu.com']"):
                    text = el.get_text(strip=True)
                    if len(text) > 10 and any(
                        kw in text for kw in ["机器人", "具身", "智能"]
                    ):
                        results.append((text, "百度资讯"))
        except Exception as e:
            print(f"  ⚠ 百度 '{q}' 出错: {e}")
    return results


def deduplicate(items):
    """按标题相似度去重"""
    seen = set()
    clean = []
    for title, source in items:
        # 规范化：去空格、去特殊标点
        key = re.sub(r"[【】\[\]「」\s]", "", title)[:40]
        h = hashlib.md5(key.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            clean.append((title, source))
    return clean


def search_all():
    """多渠道聚合搜索"""
    session = make_session()

    print("🔍 [1/3] 搜狗新闻...")
    sogou = search_sogou(session)
    print(f"       → {len(sogou)} 条")

    print("🔍 [2/3] Bing 搜索...")
    bing = search_bing(session)
    print(f"       → {len(bing)} 条")

    print("🔍 [3/3] 百度资讯...")
    baidu = search_baidu_news(session)
    print(f"       → {len(baidu)} 条")

    all_items = sogou + bing + baidu
    cleaned = deduplicate(all_items)
    print(f"   去重后共 {len(cleaned)} 条")

    return cleaned


def compose_email(news_items):
    """生成 HTML 邮件"""
    categories = {
        "🔥 融资收购": [],
        "🏭 量产与产业": [],
        "🔬 技术突破": [],
        "📊 行业动态": [],
    }

    keywords_map = {
        "🔥 融资收购": ["融资", "IPO", "轮", "亿元", "美元", "投资", "估值"],
        "🏭 量产与产业": ["量产", "产量", "万台", "产业", "工信部", "落地", "规模", "工厂", "产线"],
        "🔬 技术突破": ["发布", "Nature", "手术", "突破", "新品", "平台", "关节", "算法", "AI"],
        "📊 行业动态": [],
    }

    assigned = set()
    for cat, keywords in keywords_map.items():
        for title, source in news_items:
            if title in assigned:
                continue
            if not keywords or any(kw in title for kw in keywords):
                categories[cat].append((title, source))
                assigned.add(title)

    # 未分类的放入行业动态
    for title, source in news_items:
        if title not in assigned:
            categories["📊 行业动态"].append((title, source))

    # 统计来源
    sources = {}
    for _, src in news_items:
        sources[src] = sources.get(src, 0) + 1
    source_str = " · ".join(f"{k}({v})" for k, v in sources.items())

    html = f"""<html>
<body style="font-family: 'Microsoft YaHei', sans-serif; max-width: 700px; margin: 0 auto;">
<h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
🤖 人形机器人行业日报 — {today}
</h2>
<p style="color: #666;">来源：{source_str} | 共 {len(news_items)} 条资讯 | GitHub Actions 自动生成</p>
"""

    for cat, items in categories.items():
        if not items:
            continue
        html += f'<h3 style="color: #d93025; margin-top: 20px;">{cat}</h3><ul>'
        for title, source in items:
            html += f'<li style="margin: 6px 0;">{title} <span style="color:#999;font-size:12px">[{source}]</span></li>'
        html += "</ul>"

    html += f"""
<hr style="border: 1px solid #eee; margin-top: 30px;">
<p style="color: #999; font-size: 12px;">
本邮件由 GitHub Actions 自动运行并发送<br>
如有疑问请联系 eric_wei@atop-ks.com
</p>
<p style="color: #999; font-size: 12px;">
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
    print("🔍 多渠道搜索人形机器人资讯...")
    news = search_all()

    if not news:
        print("⚠ 未搜到任何资讯，跳过发送")
        return

    print("📧 整理日报...")
    html = compose_email(news)

    print("📤 发送邮件...")
    send_email(html)


if __name__ == "__main__":
    main()
