#!/usr/bin/env python3
"""人形机器人每日资讯 — GitHub Actions 版
每天自动搜索人形机器人行业最新资讯，整理日报并邮件发送。
"""

import os
import sys
import smtplib
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


def search_news():
    """搜索搜狗新闻"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    })

    queries = [
        "人形机器人 融资 量产",
        "人形机器人 技术突破 发布",
        "人形机器人 特斯拉 优必选 宇树",
    ]

    all_news = []
    seen = set()

    for q in queries:
        url = (
            "https://news.sogou.com/news"
            f"?query={requests.utils.quote(q)}&page=1"
        )
        try:
            resp = session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            titles = soup.select("h3 a")
            for t in titles:
                text = t.get_text(strip=True)
                if text and len(text) > 5 and text not in seen:
                    seen.add(text)
                    all_news.append((text, "搜狗新闻"))
        except Exception as e:
            print(f"  ⚠ 搜索 '{q}' 出错: {e}")

    return all_news


def compose_email(news_items):
    """生成 HTML 邮件"""
    categories = {
        "🔥 融资收购": [],
        "🏭 量产与产业": [],
        "🔬 技术突破": [],
        "📊 行业动态": [],
    }

    keywords_map = {
        "🔥 融资收购": ["融资", "IPO", "轮", "亿元", "美元", "投资"],
        "🏭 量产与产业": ["量产", "产量", "万台", "产业", "工信部", "落地", "规模"],
        "🔬 技术突破": ["发布", "Nature", "手术", "突破", "新品", "平台", "关节"],
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

    html = f"""<html>
<body style="font-family: 'Microsoft YaHei', sans-serif; max-width: 700px; margin: 0 auto;">
<h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
🤖 人形机器人行业日报 — {today}
</h2>
<p style="color: #666;">来源：搜狗新闻 | 共 {len(news_items)} 条资讯 | 由 GitHub Actions 自动生成</p>
"""

    for cat, items in categories.items():
        if not items:
            continue
        html += (
            f'<h3 style="color: #d93025; margin-top: 20px;">{cat}</h3><ul>'
        )
        for title, source in items:
            html += f'<li style="margin: 6px 0;">{title}</li>'
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
    print("🔍 搜索人形机器人资讯...")
    news = search_news()
    print(f"   搜到 {len(news)} 条去重资讯")

    if not news:
        print("⚠ 未搜到任何资讯，跳过发送")
        return

    print("📧 整理日报...")
    html = compose_email(news)

    print("📤 发送邮件...")
    send_email(html)


if __name__ == "__main__":
    main()
