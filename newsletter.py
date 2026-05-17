import json
import os
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yfinance as yf
import feedparser
import requests
from jinja2 import Template

CONFIG_PATH = Path(__file__).parent / "config.json"

BUTTONDOWN_API_KEY = os.environ.get("BUTTONDOWN_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_market_data(watchlist):
    tickers = yf.Tickers(" ".join(watchlist))
    results = []
    for symbol in watchlist:
        try:
            t = tickers.tickers[symbol]
            info = t.info
            hist = t.history(period="2d")
            if len(hist) < 2:
                continue
            prev_close = hist["Close"].iloc[-2]
            last_close = hist["Close"].iloc[-1]
            change_pct = ((last_close - prev_close) / prev_close) * 100
            results.append({
                "symbol": symbol,
                "price": last_close,
                "change_pct": change_pct,
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector", "ETF/Index"),
                "earnings_date": info.get("earningsTimestamp"),
                "recommendation": info.get("recommendationKey"),
                "target_price": info.get("targetMeanPrice"),
            })
        except Exception:
            continue
    return results


def fetch_rss_news():
    feeds = [
        ("Reuters Business", "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best"),
        ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ]
    articles = []
    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({
                    "source": name,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception:
            continue
    return articles


def fetch_fred_data(series_ids):
    if not FRED_API_KEY:
        return {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=FRED_API_KEY)
        results = {}
        labels = {
            "DFF": "Fed Funds Rate",
            "T10Y2Y": "10Y-2Y Spread",
            "T10YIE": "10Y Breakeven Inflation",
            "UNRATE": "Unemployment Rate",
            "CPIAUCSL": "CPI (All Urban)",
            "GDP": "GDP",
            "UMCSENT": "Consumer Sentiment",
        }
        for sid in series_ids:
            try:
                data = fred.get_series(sid, observation_start=datetime.date.today() - datetime.timedelta(days=90))
                if len(data) > 0:
                    latest = data.dropna().iloc[-1]
                    results[labels.get(sid, sid)] = f"{latest:.2f}"
            except Exception:
                continue
        return results
    except Exception:
        return {}


def build_html(market_data, news, macro_data, date_str):
    template = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { margin: 0; padding: 0; background-color: #f4f4f7; }
  .wrapper { width: 100%; background-color: #f4f4f7; padding: 30px 0; }
  .container { max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .header { background: #1a1a2e; padding: 24px 30px; }
  .header h1 { color: #ffffff; margin: 0; font-size: 22px; font-family: Georgia, serif; }
  .header p { color: #a0a0b0; margin: 6px 0 0 0; font-size: 13px; font-family: Arial, sans-serif; }
  .section { padding: 24px 30px; border-bottom: 1px solid #eee; }
  .section:last-child { border-bottom: none; }
  .section h2 { color: #1a1a2e; font-size: 16px; margin: 0 0 14px 0; font-family: Arial, sans-serif; text-transform: uppercase; letter-spacing: 0.5px; }
  table.data { width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; }
  table.data th { text-align: left; padding: 8px 10px; background: #f8f9fa; color: #555; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: 2px solid #e0e0e0; }
  table.data td { padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }
  table.data tr:last-child td { border-bottom: none; }
  .ticker { font-weight: 700; color: #1a1a2e; }
  .up { color: #16a34a; font-weight: 600; }
  .down { color: #dc2626; font-weight: 600; }
  .news-item { padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
  .news-item:last-child { border-bottom: none; }
  .news-item a { color: #1a1a2e; text-decoration: none; font-size: 14px; font-family: Arial, sans-serif; line-height: 1.4; }
  .news-item a:hover { text-decoration: underline; }
  .news-meta { color: #999; font-size: 11px; margin-top: 3px; font-family: Arial, sans-serif; }
  .footer { padding: 20px 30px; text-align: center; color: #999; font-size: 11px; font-family: Arial, sans-serif; }
</style>
</head>
<body>
<div class="wrapper">
<div class="container">

<div class="header">
  <h1>Daily Fundamentals Report</h1>
  <p>{{ date_str }}</p>
</div>

<div class="section">
  <h2>Market Overview</h2>
  <table class="data">
  <tr>
    <th>Ticker</th>
    <th>Price</th>
    <th>Change</th>
    <th>P/E</th>
    <th>Fwd P/E</th>
    <th>Sector</th>
  </tr>
  {% for stock in market_data %}
  <tr>
    <td class="ticker">{{ stock.symbol }}</td>
    <td>${{ "%.2f"|format(stock.price) }}</td>
    <td class="{{ 'up' if stock.change_pct >= 0 else 'down' }}">{{ "%+.2f"|format(stock.change_pct) }}%</td>
    <td>{{ "%.1f"|format(stock.pe_ratio) if stock.pe_ratio else "—" }}</td>
    <td>{{ "%.1f"|format(stock.forward_pe) if stock.forward_pe else "—" }}</td>
    <td>{{ stock.sector }}</td>
  </tr>
  {% endfor %}
  </table>
</div>

{% if macro_data %}
<div class="section">
  <h2>Macro Indicators</h2>
  <table class="data">
  <tr>
    <th>Indicator</th>
    <th>Latest Value</th>
  </tr>
  {% for name, value in macro_data.items() %}
  <tr>
    <td style="font-weight: 600;">{{ name }}</td>
    <td>{{ value }}</td>
  </tr>
  {% endfor %}
  </table>
</div>
{% endif %}

<div class="section">
  <h2>Financial News</h2>
  {% for article in news[:15] %}
  <div class="news-item">
    <a href="{{ article.link }}">{{ article.title }}</a>
    <div class="news-meta">{{ article.source }} &middot; {{ article.published }}</div>
  </div>
  {% endfor %}
</div>

<div class="footer">
  Data from Yahoo Finance, FRED, and public RSS feeds. Generated automatically.
</div>

</div>
</div>
</body>
</html>
""")
    return template.render(
        market_data=market_data,
        news=news,
        macro_data=macro_data,
        date_str=date_str,
    )


def get_subscribers():
    subscribers = []
    url = "https://api.buttondown.com/v1/subscribers"
    headers = {"Authorization": f"Token {BUTTONDOWN_API_KEY}"}
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for sub in data["results"]:
            if sub.get("subscriber_type", "regular") == "regular":
                subscribers.append(sub["email_address"])
        url = data.get("next")
    return subscribers


def send_email(subject, html_body, recipients):
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        for recipient in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = GMAIL_SENDER
            msg["To"] = recipient
            msg.attach(MIMEText(html_body, "html"))
            server.sendmail(GMAIL_SENDER, recipient, msg.as_string())
            print(f"  Sent to {recipient}")


def main():
    config = load_config()
    date_str = datetime.date.today().strftime("%A, %B %d, %Y")

    print(f"[{datetime.datetime.now()}] Fetching market data...")
    market_data = fetch_market_data(config["watchlist"])

    print(f"[{datetime.datetime.now()}] Fetching news...")
    news = fetch_rss_news()

    print(f"[{datetime.datetime.now()}] Fetching macro data...")
    macro_data = fetch_fred_data(config.get("fred_series", []))

    print(f"[{datetime.datetime.now()}] Building report...")
    html = build_html(market_data, news, macro_data, date_str)

    print(f"[{datetime.datetime.now()}] Fetching subscriber list from Buttondown...")
    subscribers = get_subscribers()
    print(f"  Found {len(subscribers)} subscriber(s)")

    subject = f"Daily Fundamentals Report — {date_str}"
    print(f"[{datetime.datetime.now()}] Sending via Gmail SMTP...")
    send_email(subject, html, subscribers)
    print(f"[{datetime.datetime.now()}] Done!")


if __name__ == "__main__":
    main()
