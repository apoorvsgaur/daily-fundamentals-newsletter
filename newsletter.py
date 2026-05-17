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
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f8f9fa;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" style="padding: 20px 10px;">
<table role="presentation" width="700" cellpadding="0" cellspacing="0" border="0" style="max-width: 700px; width: 100%;">

<tr><td style="font-family: Segoe UI, Arial, sans-serif; padding: 0 0 20px 0;">
  <h1 style="color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px; margin: 0 0 5px 0; font-size: 24px;">Daily Fundamentals Report</h1>
  <p style="color: #666; font-size: 14px; margin: 0;">{{ date_str }} | After Market Close</p>
</td></tr>

<tr><td style="background: #ffffff; padding: 20px; font-family: Segoe UI, Arial, sans-serif;">
  <h2 style="color: #16213e; margin: 0 0 15px 0; font-size: 18px;">Market Overview</h2>
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout: fixed; border-collapse: collapse;">
  <colgroup>
    <col width="60">
    <col width="80">
    <col width="70">
    <col width="50">
    <col width="55">
    <col width="*">
  </colgroup>
  <tr>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Ticker</td>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Price</td>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Chg %</td>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">P/E</td>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Fwd</td>
    <td style="padding: 6px 4px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Sector</td>
  </tr>
  {% for stock in market_data %}
  <tr style="background-color: {{ '#f9f9f9' if loop.index is odd else '#ffffff' }};">
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee; font-weight: bold;">{{ stock.symbol }}</td>
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee;">${{ "%.2f"|format(stock.price) }}</td>
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee; color: {{ '#27ae60' if stock.change_pct >= 0 else '#e74c3c' }}; font-weight: bold;">{{ "%+.2f"|format(stock.change_pct) }}%</td>
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee;">{{ "%.1f"|format(stock.pe_ratio) if stock.pe_ratio else "—" }}</td>
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee;">{{ "%.1f"|format(stock.forward_pe) if stock.forward_pe else "—" }}</td>
    <td style="padding: 5px 4px; font-size: 13px; border-bottom: 1px solid #eee;">{{ stock.sector }}</td>
  </tr>
  {% endfor %}
  </table>
</td></tr>

<tr><td style="padding: 10px 0;"></td></tr>

{% if macro_data %}
<tr><td style="background: #ffffff; padding: 20px; font-family: Segoe UI, Arial, sans-serif;">
  <h2 style="color: #16213e; margin: 0 0 15px 0; font-size: 18px;">Macro Indicators</h2>
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
  <tr>
    <td style="padding: 6px 8px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e;">Indicator</td>
    <td style="padding: 6px 8px; font-size: 12px; font-weight: bold; color: #ffffff; background-color: #16213e; border: 1px solid #16213e; width: 120px;">Value</td>
  </tr>
  {% for name, value in macro_data.items() %}
  <tr style="background-color: {{ '#f9f9f9' if loop.index is odd else '#ffffff' }};">
    <td style="padding: 5px 8px; font-size: 13px; border-bottom: 1px solid #eee; font-weight: bold;">{{ name }}</td>
    <td style="padding: 5px 8px; font-size: 13px; border-bottom: 1px solid #eee;">{{ value }}</td>
  </tr>
  {% endfor %}
  </table>
</td></tr>
<tr><td style="padding: 10px 0;"></td></tr>
{% endif %}

<tr><td style="background: #ffffff; padding: 20px; font-family: Segoe UI, Arial, sans-serif;">
  <h2 style="color: #16213e; margin: 0 0 15px 0; font-size: 18px;">Financial News</h2>
  {% for article in news[:15] %}
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
  <tr>
    <td style="border-left: 3px solid #16213e; padding: 8px 12px; background: #fafafa;">
      <a href="{{ article.link }}" style="color: #1a1a2e; text-decoration: none; font-size: 14px; font-weight: 500;">{{ article.title }}</a><br>
      <span style="color: #888; font-size: 11px;">{{ article.source }} | {{ article.published }}</span>
    </td>
  </tr>
  </table>
  {% endfor %}
</td></tr>

<tr><td style="padding: 30px 0 10px 0; text-align: center; font-family: Segoe UI, Arial, sans-serif;">
  <p style="color: #888; font-size: 12px; margin: 0;">Generated automatically. Data from Yahoo Finance, FRED, and public RSS feeds.</p>
</td></tr>

</table>
</td></tr>
</table>
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
