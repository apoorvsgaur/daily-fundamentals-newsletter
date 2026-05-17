import json
import os
import datetime
from pathlib import Path

import yfinance as yf
import feedparser
import requests
from jinja2 import Template

CONFIG_PATH = Path(__file__).parent / "config.json"

BUTTONDOWN_API_KEY = os.environ.get("BUTTONDOWN_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")


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
<head><meta charset="utf-8"></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f8f9fa;">
<h1 style="color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px;">Daily Fundamentals Report</h1>
<p style="color: #666; font-size: 14px;">{{ date_str }} | After Market Close</p>

<div style="background: white; padding: 20px; border-radius: 8px; margin: 15px 0;">
<h2 style="color: #16213e; margin-top: 0;">Market Overview</h2>
<table style="border-collapse: collapse; width: 100%; margin: 15px 0;" cellpadding="0" cellspacing="0">
<tr>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Symbol</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Price</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Change</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">P/E</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Fwd P/E</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Sector</th>
</tr>
{% for stock in market_data %}
<tr>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap;"><strong>{{ stock.symbol }}</strong></td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap;">${{ "%.2f"|format(stock.price) }}</td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap; color: {{ '#27ae60' if stock.change_pct >= 0 else '#e74c3c' }}; font-weight: bold;">{{ "%+.2f"|format(stock.change_pct) }}%</td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap;">{{ "%.1f"|format(stock.pe_ratio) if stock.pe_ratio else "—" }}</td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap;">{{ "%.1f"|format(stock.forward_pe) if stock.forward_pe else "—" }}</td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd;">{{ stock.sector }}</td>
</tr>
{% endfor %}
</table>
</div>

{% if macro_data %}
<div style="background: white; padding: 20px; border-radius: 8px; margin: 15px 0;">
<h2 style="color: #16213e; margin-top: 0;">Macro Indicators</h2>
<table style="border-collapse: collapse; width: 100%; margin: 15px 0;" cellpadding="0" cellspacing="0">
<tr>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Indicator</th>
  <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd; background-color: #16213e; color: white;">Latest Value</th>
</tr>
{% for name, value in macro_data.items() %}
<tr>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; font-weight: bold;">{{ name }}</td>
  <td style="padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd;">{{ value }}</td>
</tr>
{% endfor %}
</table>
</div>
{% endif %}

<div style="background: white; padding: 20px; border-radius: 8px; margin: 15px 0;">
<h2 style="color: #16213e; margin-top: 0;">Financial News</h2>
{% for article in news[:15] %}
<div style="margin: 12px 0; padding: 10px; background: #fafafa; border-radius: 5px; border-left: 3px solid #16213e;">
  <div><a href="{{ article.link }}" style="color: #1a1a2e; text-decoration: none; font-weight: 500;">{{ article.title }}</a></div>
  <div style="color: #888; font-size: 12px; margin-top: 4px;">{{ article.source }} | {{ article.published }}</div>
</div>
{% endfor %}
</div>

<p style="color: #888; font-size: 12px; text-align: center; margin-top: 30px;">
  Generated automatically. Data from Yahoo Finance, FRED, and public RSS feeds.
</p>
</body>
</html>
""")
    return template.render(
        market_data=market_data,
        news=news,
        macro_data=macro_data,
        date_str=date_str,
    )


def send_via_buttondown(subject, html_body):
    resp = requests.post(
        "https://api.buttondown.com/v1/emails",
        headers={
            "Authorization": f"Token {BUTTONDOWN_API_KEY}",
            "X-Buttondown-Live-Dangerously": "true",
        },
        json={
            "subject": subject,
            "body": html_body,
            "status": "about_to_send",
        },
    )
    if not resp.ok:
        print(f"Buttondown error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()


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

    subject = f"Daily Fundamentals Report — {date_str}"
    print(f"[{datetime.datetime.now()}] Sending via Buttondown...")
    result = send_via_buttondown(subject, html)
    print(f"[{datetime.datetime.now()}] Done! Email ID: {result.get('id', 'sent')}")


if __name__ == "__main__":
    main()
